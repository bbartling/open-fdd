use super::*;
use bacnet_encoding::apdu::{decode_apdu, encode_apdu, Apdu, ComplexAck, ErrorPdu, SimpleAck};
use bacnet_encoding::npdu::{decode_npdu, encode_npdu, Npdu, NpduAddress};
use bacnet_encoding::primitives::encode_property_value;
use bacnet_services::read_property::{ReadPropertyACK, ReadPropertyRequest};
use bacnet_services::rpm::{ReadAccessResult, ReadPropertyMultipleACK, ReadResultElement};
use bacnet_transport::bvll::{decode_bvll, encode_bvll};
use bacnet_types::enums::{BvlcFunction, ConfirmedServiceChoice, ErrorClass, ErrorCode};
use bytes::{Bytes, BytesMut};
use std::net::Ipv4Addr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::net::UdpSocket;
use tokio::time::{timeout, Instant};

fn encoded(value: &PropertyValue) -> Vec<u8> {
    let mut bytes = BytesMut::new();
    encode_property_value(&mut bytes, value).expect("test value encodes");
    bytes.to_vec()
}

fn result(
    level: Option<u32>,
    value: Option<&PropertyValue>,
    error: Option<(ErrorClass, ErrorCode)>,
) -> bacnet_services::rpm::ReadResultElement {
    bacnet_services::rpm::ReadResultElement {
        property_identifier: PropertyIdentifier::PRIORITY_ARRAY,
        property_array_index: level,
        property_value: value.map(encoded),
        error,
    }
}

fn empty_slots() -> (Vec<Value>, HashSet<u32>, HashSet<u32>) {
    (
        (1..=16)
            .map(|level| priority_slot_unknown(level, "missing from RPM response"))
            .collect(),
        PRIORITY_LEVELS.collect(),
        HashSet::new(),
    )
}

#[test]
fn partial_priority_rpm_is_sixteen_typed_slots_and_not_all_null() {
    let oid = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 7).unwrap();
    let zero = PropertyValue::Real(0.0);
    let false_value = PropertyValue::Boolean(false);
    let null = PropertyValue::Null;
    let response = bacnet_services::rpm::ReadPropertyMultipleACK {
        list_of_read_access_results: vec![bacnet_services::rpm::ReadAccessResult {
            object_identifier: oid,
            list_of_results: vec![
                result(Some(1), Some(&zero), None),
                result(Some(2), Some(&false_value), None),
                result(Some(3), Some(&null), None),
                result(
                    Some(4),
                    None,
                    Some((ErrorClass::PROPERTY, ErrorCode::UNKNOWN_PROPERTY)),
                ),
                result(Some(5), Some(&zero), None),
                // A malformed result must not create P0 or panic.
                result(Some(17), Some(&PropertyValue::Real(99.0)), None),
                // A duplicate makes P1 unknown until its bounded RP repair.
                result(Some(1), Some(&zero), None),
                result(None, Some(&zero), None),
            ],
        }],
    };
    let (mut slots, mut repair, mut seen) = empty_slots();
    apply_priority_rpm_results(&mut slots, &mut repair, &mut seen, &response, oid);

    assert_eq!(slots.len(), 16);
    assert_eq!(
        slots
            .iter()
            .map(|slot| slot["priority_level"].as_u64())
            .collect::<Vec<_>>(),
        (1..=16).map(Some).collect::<Vec<_>>()
    );
    assert_eq!(slots[1]["state"], "value");
    assert_eq!(slots[1]["type"], "boolean");
    assert_eq!(slots[1]["value"], false);
    assert_eq!(slots[2]["state"], "null");
    assert!(slots[2]["value"].is_null());
    assert_eq!(slots[3]["state"], "error");
    assert_eq!(slots[3]["error_kind"], "unsupported");
    assert_eq!(slots[5]["state"], "unknown");
    assert_eq!(slots[0]["state"], "error");
    assert_eq!(priority_array_state(&slots), "supported");
    assert!(slots.iter().any(|slot| slot["state"] == "unknown"));
    assert!(slots.iter().any(|slot| slot["value"].as_f64() == Some(0.0)));
}

#[test]
fn empty_priority_rpm_is_unknown_for_every_slot() {
    let oid = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 7).unwrap();
    let response = bacnet_services::rpm::ReadPropertyMultipleACK {
        list_of_read_access_results: Vec::new(),
    };
    let (mut slots, mut repair, mut seen) = empty_slots();
    apply_priority_rpm_results(&mut slots, &mut repair, &mut seen, &response, oid);
    assert_eq!(slots.len(), 16);
    assert!(slots.iter().all(|slot| slot["state"] == "unknown"));
    assert!(slots.iter().all(|slot| slot["type"] == "unknown"));
    assert_eq!(priority_array_state(&slots), "unknown");
}

#[tokio::test]
async fn dropped_write_ack_is_unknown_after_one_attempt() {
    let mut attempts = 0;
    let result = write_once(&mut attempts, || async {
        Err::<(), BacnetError>(BacnetError::Timeout(Duration::from_secs(1)))
    })
    .await;
    let outcome = classify_write_error_result(&result);
    assert_eq!(outcome, WriteOutcome::Unknown);
    assert_eq!(attempts, 1, "an ambiguous write must never be resent");
}

#[test]
fn routed_write_target_keeps_router_and_remote_mac_distinct() {
    let device = FieldDevice {
        name: "routed-device".into(),
        enabled: true,
        device_instance: 7,
        host: "192.0.2.10".into(),
        port: 47808,
        mstp_network: Some(2001),
        mstp_mac: vec![42],
        rpm_chunk: 10,
        max_apdu: 206,
        points: Vec::new(),
    };
    let target = routed_device_config(&device).expect("routed target");
    assert_eq!(target.router_mac, encode_bip_mac([192, 0, 2, 10], 47808));
    assert_eq!(target.remote_network, 2001);
    assert_eq!(target.remote_mac, vec![42]);
    assert_ne!(target.router_mac, target.remote_mac);
}

#[test]
fn object_list_duplicate_remains_pending_until_correlated_repair() {
    let first = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 1).unwrap();
    let second = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 2).unwrap();
    let mut objects_by_index = HashMap::new();
    let mut missing_indexes = HashSet::from([1]);
    let mut invalid_indexes = HashSet::new();
    let mut errors = Vec::new();

    record_object_list_value(
        &mut objects_by_index,
        &mut missing_indexes,
        &mut invalid_indexes,
        &mut errors,
        1,
        first,
    );
    assert_eq!(objects_by_index.get(&1), Some(&first));
    assert!(!missing_indexes.contains(&1));

    record_object_list_value(
        &mut objects_by_index,
        &mut missing_indexes,
        &mut invalid_indexes,
        &mut errors,
        1,
        second,
    );
    assert!(!objects_by_index.contains_key(&1));
    assert!(missing_indexes.contains(&1));
    assert!(invalid_indexes.contains(&1));

    // A third duplicate is still untrusted. It cannot make discovery look
    // complete; only the exact RP repair below may clear the index.
    record_object_list_value(
        &mut objects_by_index,
        &mut missing_indexes,
        &mut invalid_indexes,
        &mut errors,
        1,
        first,
    );
    assert!(!objects_by_index.contains_key(&1));
    assert!(missing_indexes.contains(&1));
    assert_eq!(errors.len(), 1);

    objects_by_index.insert(1, second);
    missing_indexes.remove(&1);
    invalid_indexes.remove(&1);
    assert_eq!(objects_by_index.get(&1), Some(&second));
    assert!(!missing_indexes.contains(&1));
    assert!(!invalid_indexes.contains(&1));
}

#[test]
fn commandability_requires_correlated_complete_unsigned_sixteen() {
    let oid = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 7).unwrap();
    let supported = bacnet_services::rpm::ReadPropertyMultipleACK {
        list_of_read_access_results: vec![bacnet_services::rpm::ReadAccessResult {
            object_identifier: oid,
            list_of_results: vec![result(Some(0), Some(&PropertyValue::Unsigned(16)), None)],
        }],
    };
    assert_eq!(
        commandability_from_rpm_response(&supported, oid),
        Commandability::Supported
    );

    for value in [
        PropertyValue::Null,
        PropertyValue::Boolean(false),
        PropertyValue::Unsigned(15),
    ] {
        let response = bacnet_services::rpm::ReadPropertyMultipleACK {
            list_of_read_access_results: vec![bacnet_services::rpm::ReadAccessResult {
                object_identifier: oid,
                list_of_results: vec![result(Some(0), Some(&value), None)],
            }],
        };
        assert_eq!(
            commandability_from_rpm_response(&response, oid),
            Commandability::Unknown
        );
    }

    let wrong_object = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 8).unwrap();
    let wrong_object_response = bacnet_services::rpm::ReadPropertyMultipleACK {
        list_of_read_access_results: vec![bacnet_services::rpm::ReadAccessResult {
            object_identifier: wrong_object,
            list_of_results: vec![result(Some(0), Some(&PropertyValue::Unsigned(16)), None)],
        }],
    };
    assert_eq!(
        commandability_from_rpm_response(&wrong_object_response, oid),
        Commandability::Unknown
    );

    let conflicting = bacnet_services::rpm::ReadPropertyMultipleACK {
        list_of_read_access_results: vec![bacnet_services::rpm::ReadAccessResult {
            object_identifier: oid,
            list_of_results: vec![
                result(Some(0), Some(&PropertyValue::Unsigned(16)), None),
                result(Some(0), Some(&PropertyValue::Unsigned(15)), None),
            ],
        }],
    };
    assert_eq!(
        commandability_from_rpm_response(&conflicting, oid),
        Commandability::Unknown
    );

    let malformed = bacnet_services::rpm::ReadPropertyMultipleACK {
        list_of_read_access_results: vec![bacnet_services::rpm::ReadAccessResult {
            object_identifier: oid,
            list_of_results: vec![bacnet_services::rpm::ReadResultElement {
                property_identifier: PropertyIdentifier::PRIORITY_ARRAY,
                property_array_index: Some(0),
                property_value: Some(vec![0x00]),
                error: None,
            }],
        }],
    };
    assert_eq!(
        commandability_from_rpm_response(&malformed, oid),
        Commandability::Unknown
    );
}

#[test]
fn commandability_rp_errors_distinguish_unsupported_from_timeout() {
    assert_eq!(
        commandability_from_error_codes(ErrorClass::PROPERTY, ErrorCode::UNKNOWN_PROPERTY),
        Commandability::Unsupported
    );
    assert_eq!(
        commandability_from_error_codes(ErrorClass::DEVICE, ErrorCode::OTHER),
        Commandability::Unknown
    );
    let timeout_error = BacnetError::Timeout(Duration::from_millis(1));
    assert!(!is_unsupported_bacnet_error(&timeout_error));
    assert_eq!(classify_write_error(&timeout_error), WriteOutcome::Unknown);

    let oid = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 7).unwrap();
    let malformed_ack = bacnet_services::read_property::ReadPropertyACK {
        object_identifier: oid,
        property_identifier: PropertyIdentifier::PRIORITY_ARRAY,
        property_array_index: Some(0),
        property_value: vec![0x00],
    };
    assert_eq!(
        commandability_from_priority_read_result(Ok(malformed_ack), oid, Commandability::Unknown),
        Commandability::Unknown
    );
    assert_eq!(
        commandability_from_priority_read_result(
            Err(BacnetError::Protocol {
                class: ErrorClass::PROPERTY.to_raw() as u32,
                code: ErrorCode::UNKNOWN_PROPERTY.to_raw() as u32,
            }),
            oid,
            Commandability::Unknown,
        ),
        Commandability::Unsupported
    );
    assert_eq!(
        commandability_from_priority_read_result(Err(timeout_error), oid, Commandability::Unknown,),
        Commandability::Unknown
    );
}

fn write_test_config(port: u16) -> PathBuf {
    let path = std::env::temp_dir().join(format!(
        "openfdd-bacnet-write-test-{}-{}.toml",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock after epoch")
            .as_nanos()
    ));
    let config = format!(
        "[[devices]]\nname = \"routed-write-test\"\nenabled = true\ndevice_instance = 5007\nhost = \"127.0.0.1\"\nport = {port}\nmstp_network = 2001\nmstp_mac = [42]\nrpm_chunk = 10\nmax_apdu = 480\npoints = []\n"
    );
    std::fs::write(&path, config).expect("write synthetic BACnet test catalog");
    path
}

fn offline_test_config(port: u16) -> PathBuf {
    let path = std::env::temp_dir().join(format!(
        "openfdd-bacnet-offline-test-{}-{}.toml",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock after epoch")
            .as_nanos()
    ));
    let config = format!(
        "[[devices]]\nname = \"offline-discovery-test\"\nenabled = true\ndevice_instance = 5008\nhost = \"127.0.0.1\"\nport = {port}\nrpm_chunk = 10\nmax_apdu = 480\npoints = []\n"
    );
    std::fs::write(&path, config).expect("write synthetic offline BACnet catalog");
    path
}

fn write_test_settings(path: PathBuf) -> Settings {
    let mut settings = Settings {
        field_devices_toml: path,
        ..Settings::default()
    };
    settings.bacnet_client.interface = Ipv4Addr::LOCALHOST;
    settings.bacnet_client.broadcast = Ipv4Addr::LOCALHOST;
    settings.bacnet_client.read_bind_port = 0;
    settings.bacnet_client.whois_bind_port = 0;
    settings.bacnet_client.apdu_timeout_ms = 25;
    settings.bacnet_client.whois_timeout_secs = 0.01;
    settings.bacnet_server.interface = Ipv4Addr::LOCALHOST;
    settings
}

fn write_service_frame(data: &[u8]) -> Option<bool> {
    let bvll = decode_bvll(data).ok()?;
    let npdu = decode_npdu(bvll.payload).ok()?;
    if npdu.is_network_message {
        return None;
    }
    let Apdu::ConfirmedRequest(request) = decode_apdu(npdu.payload).ok()? else {
        return None;
    };
    if request.service_choice != bacnet_types::enums::ConfirmedServiceChoice::WRITE_PROPERTY {
        return None;
    }
    Some(
        npdu.destination
            == Some(NpduAddress {
                network: 2001,
                mac_address: vec![42].into(),
            }),
    )
}

#[derive(Clone, Copy)]
enum WriteVerificationMode {
    CorrectWrite,
    CorrectRelease,
    Mismatch,
    ReadbackTimeout,
    WrongObject,
    WrongProperty,
    WrongIndex,
    TrailingBytes,
    Reject,
}

fn response_frame(apdu: Apdu) -> Vec<u8> {
    let mut apdu_bytes = BytesMut::new();
    encode_apdu(&mut apdu_bytes, &apdu).expect("encode fake APDU");
    let npdu = Npdu {
        expecting_reply: false,
        payload: Bytes::from(apdu_bytes.to_vec()),
        ..Npdu::default()
    };
    let mut npdu_bytes = BytesMut::new();
    encode_npdu(&mut npdu_bytes, &npdu).expect("encode fake NPDU");
    let mut frame = BytesMut::new();
    encode_bvll(&mut frame, BvlcFunction::ORIGINAL_UNICAST_NPDU, &npdu_bytes)
        .expect("encode fake BVLL");
    frame.to_vec()
}

fn simple_ack_frame(request: &bacnet_encoding::apdu::ConfirmedRequest) -> Vec<u8> {
    response_frame(Apdu::SimpleAck(SimpleAck {
        invoke_id: request.invoke_id,
        service_choice: request.service_choice,
    }))
}

fn error_frame(request: &bacnet_encoding::apdu::ConfirmedRequest) -> Vec<u8> {
    response_frame(Apdu::Error(ErrorPdu {
        invoke_id: request.invoke_id,
        service_choice: request.service_choice,
        error_class: ErrorClass::PROPERTY,
        error_code: ErrorCode::OTHER,
        error_data: Bytes::new(),
    }))
}

fn read_property_ack_frame(
    request: &bacnet_encoding::apdu::ConfirmedRequest,
    object_identifier: ObjectIdentifier,
    property_identifier: PropertyIdentifier,
    property_array_index: Option<u32>,
    property_value: Vec<u8>,
) -> Vec<u8> {
    let mut service = BytesMut::new();
    ReadPropertyACK {
        object_identifier,
        property_identifier,
        property_array_index,
        property_value,
    }
    .encode(&mut service);
    response_frame(Apdu::ComplexAck(ComplexAck {
        segmented: false,
        more_follows: false,
        invoke_id: request.invoke_id,
        sequence_number: None,
        proposed_window_size: None,
        service_choice: ConfirmedServiceChoice::READ_PROPERTY,
        service_ack: Bytes::from(service.to_vec()),
    }))
}

fn verification_test_config(port: u16) -> PathBuf {
    let path = std::env::temp_dir().join(format!(
        "openfdd-bacnet-verification-test-{}-{}.toml",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock after epoch")
            .as_nanos()
    ));
    let config = format!(
        "[[devices]]\nname = \"write-verification-test\"\nenabled = true\ndevice_instance = 5011\nhost = \"127.0.0.1\"\nport = {port}\nrpm_chunk = 10\nmax_apdu = 480\npoints = []\n"
    );
    std::fs::write(&path, config).expect("write synthetic verification catalog");
    path
}

async fn spawn_write_verifier(
    socket: UdpSocket,
    mode: WriteVerificationMode,
) -> (
    Arc<std::sync::atomic::AtomicUsize>,
    Arc<std::sync::atomic::AtomicUsize>,
    tokio::task::JoinHandle<()>,
) {
    use std::sync::atomic::{AtomicUsize, Ordering};

    let write_count = Arc::new(AtomicUsize::new(0));
    let read_count = Arc::new(AtomicUsize::new(0));
    let writes = Arc::clone(&write_count);
    let reads = Arc::clone(&read_count);
    let task = tokio::spawn(async move {
        let mut buffer = [0u8; 4096];
        loop {
            let Ok(Ok((len, peer))) =
                timeout(Duration::from_secs(2), socket.recv_from(&mut buffer)).await
            else {
                break;
            };
            let Some(bvll) = decode_bvll(&buffer[..len]).ok() else {
                continue;
            };
            let Some(npdu) = decode_npdu(bvll.payload).ok() else {
                continue;
            };
            let Ok(apdu) = decode_apdu(npdu.payload) else {
                continue;
            };
            let Apdu::ConfirmedRequest(request) = apdu else {
                continue;
            };
            let response = match request.service_choice {
                ConfirmedServiceChoice::WRITE_PROPERTY => {
                    writes.fetch_add(1, Ordering::SeqCst);
                    if matches!(mode, WriteVerificationMode::Reject) {
                        error_frame(&request)
                    } else {
                        simple_ack_frame(&request)
                    }
                }
                ConfirmedServiceChoice::READ_PROPERTY => {
                    reads.fetch_add(1, Ordering::SeqCst);
                    if matches!(mode, WriteVerificationMode::ReadbackTimeout) {
                        continue;
                    }
                    let Ok(read) = ReadPropertyRequest::decode(&request.service_request) else {
                        continue;
                    };
                    let expected_oid = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 7)
                        .expect("test object identifier");
                    let mut ack_oid = expected_oid;
                    let mut ack_pid = read.property_identifier;
                    let mut ack_index = read.property_array_index;
                    let is_selected = read.property_identifier
                        == PropertyIdentifier::PRIORITY_ARRAY
                        && read.property_array_index == Some(8);
                    let mut value = if is_selected {
                        if matches!(mode, WriteVerificationMode::CorrectRelease) {
                            PropertyValue::Null
                        } else {
                            PropertyValue::Real(42.0)
                        }
                    } else {
                        PropertyValue::Real(42.0)
                    };
                    match mode {
                        WriteVerificationMode::Mismatch if is_selected => {
                            value = PropertyValue::Real(41.0)
                        }
                        WriteVerificationMode::WrongObject if is_selected => {
                            ack_oid = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 8)
                                .expect("wrong test object identifier")
                        }
                        WriteVerificationMode::WrongProperty if is_selected => {
                            ack_pid = PropertyIdentifier::PRESENT_VALUE
                        }
                        WriteVerificationMode::WrongIndex if is_selected => ack_index = Some(7),
                        _ => {}
                    }
                    let mut encoded_value = encoded(&value);
                    if matches!(mode, WriteVerificationMode::TrailingBytes) && is_selected {
                        encoded_value.push(0);
                    }
                    read_property_ack_frame(&request, ack_oid, ack_pid, ack_index, encoded_value)
                }
                _ => continue,
            };
            let _ = socket.send_to(&response, peer).await;
        }
    });
    (write_count, read_count, task)
}

async fn run_verified_write(mode: WriteVerificationMode, release: bool) -> (Value, usize, usize) {
    let socket = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0))
        .await
        .expect("bind verification receiver");
    let port = socket
        .local_addr()
        .expect("verification receiver address")
        .port();
    let config = verification_test_config(port);
    let service = BacnetClientService::new(write_test_settings(config.clone()))
        .expect("construct verification service");
    let (writes, reads, task) = spawn_write_verifier(socket, mode).await;
    let result = service
        .write_property(
            5011,
            "analog-value",
            7,
            if release { None } else { Some(json!(42.0)) },
            "present-value",
            Some(8),
            Some("real"),
        )
        .await
        .expect("write route should return typed outcome");
    let write_count = writes.load(std::sync::atomic::Ordering::SeqCst);
    let read_count = reads.load(std::sync::atomic::Ordering::SeqCst);
    task.abort();
    let _ = std::fs::remove_file(config);
    (result, write_count, read_count)
}

#[derive(Clone, Copy)]
enum PriorityRepairMode {
    Valid,
    WrongObject,
    WrongProperty,
    WrongIndex,
    TrailingBytes,
}

fn rpm_priority_frame(
    request: &bacnet_encoding::apdu::ConfirmedRequest,
    oid: ObjectIdentifier,
) -> Vec<u8> {
    let mut results = Vec::new();
    for level in 1..=16 {
        if level == 8 {
            continue;
        }
        results.push(ReadResultElement {
            property_identifier: PropertyIdentifier::PRIORITY_ARRAY,
            property_array_index: Some(level),
            property_value: Some(encoded(&PropertyValue::Null)),
            error: None,
        });
    }
    let mut service = BytesMut::new();
    ReadPropertyMultipleACK {
        list_of_read_access_results: vec![ReadAccessResult {
            object_identifier: oid,
            list_of_results: results,
        }],
    }
    .encode(&mut service);
    response_frame(Apdu::ComplexAck(ComplexAck {
        segmented: false,
        more_follows: false,
        invoke_id: request.invoke_id,
        sequence_number: None,
        proposed_window_size: None,
        service_choice: ConfirmedServiceChoice::READ_PROPERTY_MULTIPLE,
        service_ack: Bytes::from(service.to_vec()),
    }))
}

fn priority_repair_test_config(port: u16) -> PathBuf {
    let path = std::env::temp_dir().join(format!(
        "openfdd-bacnet-priority-repair-test-{}-{}.toml",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock after epoch")
            .as_nanos()
    ));
    let config = format!(
        "[[devices]]\nname = \"priority-repair-test\"\nenabled = true\ndevice_instance = 5012\nhost = \"127.0.0.1\"\nport = {port}\nrpm_chunk = 10\nmax_apdu = 480\npoints = []\n"
    );
    std::fs::write(&path, config).expect("write synthetic priority repair catalog");
    path
}

async fn run_priority_repair(mode: PriorityRepairMode) -> Value {
    let socket = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0))
        .await
        .expect("bind priority repair receiver");
    let port = socket
        .local_addr()
        .expect("priority repair receiver address")
        .port();
    let config = priority_repair_test_config(port);
    let service = BacnetClientService::new(write_test_settings(config.clone()))
        .expect("construct priority repair service");
    let task = tokio::spawn(async move {
        let oid = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 7)
            .expect("priority repair object identifier");
        let mut buffer = [0u8; 4096];
        loop {
            let Ok(Ok((len, peer))) =
                timeout(Duration::from_secs(2), socket.recv_from(&mut buffer)).await
            else {
                break;
            };
            let Some(bvll) = decode_bvll(&buffer[..len]).ok() else {
                continue;
            };
            let Some(npdu) = decode_npdu(bvll.payload).ok() else {
                continue;
            };
            let Ok(Apdu::ConfirmedRequest(request)) = decode_apdu(npdu.payload) else {
                continue;
            };
            let response = match request.service_choice {
                ConfirmedServiceChoice::READ_PROPERTY_MULTIPLE => rpm_priority_frame(&request, oid),
                ConfirmedServiceChoice::READ_PROPERTY => {
                    let Ok(read) = ReadPropertyRequest::decode(&request.service_request) else {
                        continue;
                    };
                    let mut ack_oid = oid;
                    let mut ack_pid = read.property_identifier;
                    let mut ack_index = read.property_array_index;
                    match mode {
                        PriorityRepairMode::WrongObject => {
                            ack_oid = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 8)
                                .expect("wrong priority object identifier")
                        }
                        PriorityRepairMode::WrongProperty => {
                            ack_pid = PropertyIdentifier::PRESENT_VALUE
                        }
                        PriorityRepairMode::WrongIndex => ack_index = Some(7),
                        PriorityRepairMode::Valid | PriorityRepairMode::TrailingBytes => {}
                    }
                    let mut value = encoded(&PropertyValue::Real(42.0));
                    if matches!(mode, PriorityRepairMode::TrailingBytes) {
                        value.push(0);
                    }
                    read_property_ack_frame(&request, ack_oid, ack_pid, ack_index, value)
                }
                _ => continue,
            };
            let _ = socket.send_to(&response, peer).await;
        }
    });
    let result = service
        .read_priority_array(5012, "analog-value", 7)
        .await
        .expect("priority-array read should return typed slots");
    task.abort();
    let _ = std::fs::remove_file(config);
    result
}

fn commandability_test_config(port: u16) -> PathBuf {
    let path = std::env::temp_dir().join(format!(
        "openfdd-bacnet-commandability-test-{}-{}.toml",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock after epoch")
            .as_nanos()
    ));
    let config = format!(
        "[[devices]]\nname = \"commandability-test\"\nenabled = true\ndevice_instance = 5013\nhost = \"127.0.0.1\"\nport = {port}\nrpm_chunk = 10\nmax_apdu = 480\npoints = []\n"
    );
    std::fs::write(&path, config).expect("write synthetic commandability catalog");
    path
}

#[tokio::test]
async fn production_write_timeout_sends_one_routed_request_with_retries_disabled() {
    let socket = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0))
        .await
        .expect("bind dropped-ACK loopback receiver");
    let port = socket.local_addr().expect("receiver address").port();
    let config = write_test_config(port);
    let service = BacnetClientService::new(write_test_settings(config.clone()))
        .expect("construct BACnet service");

    let mut write_task = Box::pin(service.write_property(
        5007,
        "analog-value",
        7,
        None,
        "present-value",
        Some(8),
        None,
    ));
    let mut buffer = [0u8; 2048];
    let mut write_frames = 0;
    let mut routed_frames = 0;
    let result = loop {
        tokio::select! {
            result = &mut write_task => break result.expect("write task should resolve"),
            datagram = timeout(Duration::from_secs(1), socket.recv_from(&mut buffer)) => {
                let (len, _) = datagram.expect("loopback receive should not time out").expect("receive frame");
                if let Some(routed) = write_service_frame(&buffer[..len]) {
                    write_frames += 1;
                    routed_frames += usize::from(routed);
                }
            }
        }
    };

    // Drain the socket briefly to catch a late retransmission. A retries=0
    // production client must leave exactly one WriteProperty invocation.
    let drain_deadline = Instant::now() + Duration::from_millis(120);
    while Instant::now() < drain_deadline {
        let remaining = drain_deadline.saturating_duration_since(Instant::now());
        let Ok(Ok((len, _))) = timeout(remaining, socket.recv_from(&mut buffer)).await else {
            break;
        };
        if let Some(routed) = write_service_frame(&buffer[..len]) {
            write_frames += 1;
            routed_frames += usize::from(routed);
        }
    }
    let _ = std::fs::remove_file(config);

    assert_eq!(write_frames, 1, "dropped ACK must not trigger a resend");
    assert_eq!(
        routed_frames, 1,
        "the one write must preserve the routed target"
    );
    assert_eq!(result["ok"], false, "unexpected write result: {result}");
    assert_eq!(
        result["status"], "unknown",
        "unexpected write result: {result}"
    );
    assert_eq!(
        result["outcome"], "unknown",
        "unexpected write result: {result}"
    );
    assert_eq!(result["write_attempts"], 1);
    assert_eq!(result["released"], false);
    assert_eq!(result["verified"], false);
}

#[tokio::test]
async fn acknowledged_write_requires_selected_slot_and_present_value_readback() {
    let (result, write_count, read_count) =
        run_verified_write(WriteVerificationMode::CorrectWrite, false).await;
    assert_eq!(
        write_count, 1,
        "verification must never retransmit WriteProperty"
    );
    assert_eq!(read_count, 2, "verification reads the selected slot and PV");
    assert_eq!(result["ok"], true, "unexpected write result: {result}");
    assert_eq!(result["status"], "success");
    assert_eq!(result["outcome"], "acknowledged");
    assert_eq!(result["verified"], true);
    assert_eq!(result["verification"], "readback");
    assert_eq!(result["readback"]["selected_priority_tag"], "real");
    assert_eq!(result["readback"]["property_tag"], "real");
}

#[tokio::test]
async fn acknowledged_release_requires_null_selected_slot_readback() {
    let (result, write_count, read_count) =
        run_verified_write(WriteVerificationMode::CorrectRelease, true).await;
    assert_eq!(write_count, 1);
    assert_eq!(read_count, 2);
    assert_eq!(result["ok"], true, "unexpected release result: {result}");
    assert_eq!(result["released"], true);
    assert_eq!(result["verified"], true);
    assert_eq!(result["verification"], "readback");
    assert_eq!(result["readback"]["selected_priority_tag"], "null");
}

#[tokio::test]
async fn acknowledged_write_mismatch_is_failed_without_resend() {
    let (result, write_count, read_count) =
        run_verified_write(WriteVerificationMode::Mismatch, false).await;
    assert_eq!(write_count, 1);
    assert_eq!(
        read_count, 1,
        "PV must not be read after selected-slot mismatch"
    );
    assert_eq!(result["ok"], false, "unexpected mismatch result: {result}");
    assert_eq!(result["status"], "failed");
    assert_eq!(result["outcome"], "failed");
    assert_eq!(result["verified"], false);
    assert_eq!(result["released"], false);
    assert_eq!(result["transmission_acknowledged"], true);
}

#[tokio::test]
async fn acknowledged_write_readback_timeout_is_unknown_without_resend() {
    let (result, write_count, read_count) =
        run_verified_write(WriteVerificationMode::ReadbackTimeout, false).await;
    assert_eq!(write_count, 1);
    assert_eq!(read_count, 1);
    assert_eq!(result["ok"], false, "unexpected timeout result: {result}");
    assert_eq!(result["status"], "unknown");
    assert_eq!(result["outcome"], "unknown");
    assert_eq!(result["verified"], false);
    assert_eq!(result["released"], false);
    assert_eq!(result["transmission_acknowledged"], true);
}

#[tokio::test]
async fn rejected_release_is_not_reported_as_released_or_verified() {
    let (result, write_count, read_count) =
        run_verified_write(WriteVerificationMode::Reject, true).await;
    assert_eq!(write_count, 1);
    assert_eq!(
        read_count, 0,
        "rejected WriteProperty must not be read back"
    );
    assert_eq!(result["ok"], false, "unexpected rejection result: {result}");
    assert_eq!(result["status"], "rejected");
    assert_eq!(result["outcome"], "rejected");
    assert_eq!(result["released"], false);
    assert_eq!(result["verified"], false);
    assert_eq!(result["transmission_acknowledged"], false);
}

#[tokio::test]
async fn readback_rejects_wrong_correlation_and_trailing_bytes() {
    for mode in [
        WriteVerificationMode::WrongObject,
        WriteVerificationMode::WrongProperty,
        WriteVerificationMode::WrongIndex,
        WriteVerificationMode::TrailingBytes,
    ] {
        let (result, write_count, read_count) = run_verified_write(mode, false).await;
        assert_eq!(
            write_count, 1,
            "unexpected write count for malformed readback"
        );
        assert_eq!(
            read_count, 1,
            "malformed selected-slot readback should stop verification"
        );
        assert_eq!(result["ok"], false, "unexpected malformed result: {result}");
        assert_eq!(result["status"], "unknown");
        assert_eq!(result["outcome"], "unknown");
        assert_eq!(result["verified"], false);
        assert_eq!(result["released"], false);
    }
}

#[tokio::test]
async fn priority_array_repair_correlates_object_property_index_and_value_bytes() {
    let valid = run_priority_repair(PriorityRepairMode::Valid).await;
    assert_eq!(valid["priority_array"].as_array().unwrap().len(), 16);
    assert_eq!(valid["priority_array"][7]["state"], "value");
    assert_eq!(valid["priority_array"][7]["value"], 42.0);

    for mode in [
        PriorityRepairMode::WrongObject,
        PriorityRepairMode::WrongProperty,
        PriorityRepairMode::WrongIndex,
        PriorityRepairMode::TrailingBytes,
    ] {
        let result = run_priority_repair(mode).await;
        let slots = result["priority_array"].as_array().unwrap();
        assert_eq!(slots.len(), 16);
        assert_eq!(slots[7]["state"], "unknown");
        assert!(slots[7]["repair_error"].is_string());
        assert_ne!(result["priority_array_state"], "unsupported");
    }
}

#[tokio::test]
async fn commandability_uses_valid_rp_after_rpm_failure() {
    use std::sync::atomic::{AtomicUsize, Ordering};

    let socket = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0))
        .await
        .expect("bind commandability receiver");
    let port = socket
        .local_addr()
        .expect("commandability receiver address")
        .port();
    let config = commandability_test_config(port);
    let service = BacnetClientService::new(write_test_settings(config.clone()))
        .expect("construct commandability service");
    let rpm_count = Arc::new(AtomicUsize::new(0));
    let rp_count = Arc::new(AtomicUsize::new(0));
    let rpm_seen = Arc::clone(&rpm_count);
    let rp_seen = Arc::clone(&rp_count);
    let task = tokio::spawn(async move {
        let oid = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 7)
            .expect("commandability object identifier");
        let mut buffer = [0u8; 4096];
        loop {
            let Ok(Ok((len, peer))) =
                timeout(Duration::from_secs(2), socket.recv_from(&mut buffer)).await
            else {
                break;
            };
            let Some(bvll) = decode_bvll(&buffer[..len]).ok() else {
                continue;
            };
            let Some(npdu) = decode_npdu(bvll.payload).ok() else {
                continue;
            };
            let Ok(Apdu::ConfirmedRequest(request)) = decode_apdu(npdu.payload) else {
                continue;
            };
            let response = match request.service_choice {
                ConfirmedServiceChoice::READ_PROPERTY_MULTIPLE => {
                    rpm_seen.fetch_add(1, Ordering::SeqCst);
                    error_frame(&request)
                }
                ConfirmedServiceChoice::READ_PROPERTY => {
                    rp_seen.fetch_add(1, Ordering::SeqCst);
                    read_property_ack_frame(
                        &request,
                        oid,
                        PropertyIdentifier::PRIORITY_ARRAY,
                        Some(0),
                        encoded(&PropertyValue::Unsigned(16)),
                    )
                }
                _ => continue,
            };
            let _ = socket.send_to(&response, peer).await;
        }
    });

    let oid = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 7).unwrap();
    let device = service.find_device(5013).expect("configured test device");
    let mut client = service
        .new_client(Some(device))
        .await
        .expect("build commandability client");
    service
        .seed_field_device(&client, device)
        .await
        .expect("seed commandability device");
    let states = service
        .probe_commandability_batch(&client, 5013, &[oid])
        .await;
    let _ = client.stop().await;
    task.abort();
    let _ = std::fs::remove_file(config);

    assert_eq!(rpm_count.load(Ordering::SeqCst), 1);
    assert_eq!(rp_count.load(Ordering::SeqCst), 1);
    assert_eq!(states.get(&oid), Some(&Commandability::Supported));
}

#[tokio::test]
async fn slow_background_scan_yields_bus_to_interactive_read() {
    let slow_socket = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0))
        .await
        .expect("bind slow scan receiver");
    let slow_port = slow_socket
        .local_addr()
        .expect("slow scan receiver address")
        .port();
    let fast_socket = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0))
        .await
        .expect("bind interactive receiver");
    let fast_port = fast_socket
        .local_addr()
        .expect("interactive receiver address")
        .port();
    let config = std::env::temp_dir().join(format!(
        "openfdd-bacnet-scan-fairness-{}-{}.toml",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock after epoch")
            .as_nanos()
    ));
    std::fs::write(
        &config,
        format!(
            "[[devices]]\nname = \"slow-scan\"\nenabled = true\ndevice_instance = 5014\nhost = \"127.0.0.1\"\nport = {slow_port}\nrpm_chunk = 10\nmax_apdu = 480\npoints = []\n\n[[devices]]\nname = \"fast-interactive\"\nenabled = true\ndevice_instance = 5015\nhost = \"127.0.0.1\"\nport = {fast_port}\nrpm_chunk = 10\nmax_apdu = 480\npoints = []\n"
        ),
    )
    .expect("write scan fairness catalog");
    let service = Arc::new(
        BacnetClientService::new(write_test_settings(config.clone()))
            .expect("construct scan fairness service"),
    );

    let discovery = tokio::spawn({
        let service = Arc::clone(&service);
        async move { service.point_discovery(5014).await }
    });
    let mut slow_buffer = [0u8; 4096];
    let (slow_len, _) = timeout(
        Duration::from_millis(200),
        slow_socket.recv_from(&mut slow_buffer),
    )
    .await
    .expect("slow scan should issue a bounded request")
    .expect("slow scan datagram");
    assert!(slow_len > 0);

    let fast_task = tokio::spawn(async move {
        let mut buffer = [0u8; 4096];
        let Ok(Ok((len, peer))) =
            timeout(Duration::from_secs(1), fast_socket.recv_from(&mut buffer)).await
        else {
            return;
        };
        let Some(bvll) = decode_bvll(&buffer[..len]).ok() else {
            return;
        };
        let Some(npdu) = decode_npdu(bvll.payload).ok() else {
            return;
        };
        let Ok(Apdu::ConfirmedRequest(request)) = decode_apdu(npdu.payload) else {
            return;
        };
        if request.service_choice == ConfirmedServiceChoice::READ_PROPERTY {
            let oid = ObjectIdentifier::new(ObjectType::ANALOG_VALUE, 7).unwrap();
            let response = read_property_ack_frame(
                &request,
                oid,
                PropertyIdentifier::PRESENT_VALUE,
                None,
                encoded(&PropertyValue::Real(12.5)),
            );
            let _ = fast_socket.send_to(&response, peer).await;
        }
    });

    let started = Instant::now();
    let result = timeout(
        Duration::from_millis(250),
        service.read_property(5015, "analog-value", 7, "present-value"),
    )
    .await
    .expect("interactive read must not wait for the whole slow scan")
    .expect("interactive read should receive its response");
    let latency = started.elapsed();
    assert!(
        latency < Duration::from_millis(200),
        "interactive read latency was {latency:?}"
    );
    assert_eq!(result["tag"], "real");
    assert_eq!(result["value"], 12.5);

    discovery.abort();
    let _ = discovery.await;
    let _ = fast_task.await;
    drop(slow_socket);
    let _ = std::fs::remove_file(config);
}

#[tokio::test]
async fn scan_scheduler_bounds_admission_and_releases_permit_on_cancellation() {
    let socket = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0))
        .await
        .expect("bind offline discovery receiver");
    let port = socket.local_addr().expect("receiver address").port();
    let config = offline_test_config(port);
    let service = Arc::new(
        BacnetClientService::new(write_test_settings(config.clone()))
            .expect("construct BACnet service"),
    );

    let first = tokio::spawn({
        let service = Arc::clone(&service);
        async move { service.point_discovery(5008).await }
    });
    let second = tokio::spawn({
        let service = Arc::clone(&service);
        async move { service.point_discovery(5008).await }
    });
    tokio::task::yield_now().await;
    let third = tokio::spawn({
        let service = Arc::clone(&service);
        async move { service.point_discovery(5008).await }
    });
    let mut buffer = [0u8; 2048];
    let (len, _) = timeout(Duration::from_millis(200), socket.recv_from(&mut buffer))
        .await
        .expect("first scan must own the socket")
        .expect("receive discovery datagram");
    assert!(len > 0);
    let third_result = timeout(Duration::from_millis(100), third)
        .await
        .expect("third scan must be rejected by bounded admission")
        .expect("third scan task should not panic");
    assert!(third_result
        .expect_err("third scan should be rejected")
        .contains("queue full"));

    // Cancel one admitted scan. Dropping its task must release the active
    // permit so the queued scan can make progress without a socket flood.
    first.abort();
    let _ = first.await;
    let _ = timeout(Duration::from_millis(500), second)
        .await
        .expect("offline discovery must complete within its bounded retries")
        .expect("discovery task should not panic");
    let _ = std::fs::remove_file(config);
}
