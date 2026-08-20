from pathlib import Path

path = Path('services/central/src/analytics/plant_health.rs')
s = path.read_text()
old = '''            let mut ids: Vec<String> = index
                .iter()
                .filter_map(|(eq, rules)| {
                    rules
                        .keys()
                        .any(|rule| rule_ids.contains(rule.as_str()))
                        .then(|| eq.clone())
                })
                .collect();
'''
new = '''            let mut ids: Vec<String> = index
                .iter()
                .filter(|(_, rules)| {
                    rules
                        .keys()
                        .any(|rule| rule_ids.contains(rule.as_str()))
                })
                .map(|(eq, _)| eq.clone())
                .collect();
'''
if old not in s:
    raise SystemExit('filter_map anchor not found')
s = s.replace(old, new, 1)
old = '''
    #[test]
    fn sensor_spec_is_faults_only_for_clean_rows_empty_contract() {
        assert!(SENSOR_SPEC.faults_only);
    }
'''
if old not in s:
    raise SystemExit('constant assertion test anchor not found')
s = s.replace(old, '\n', 1)
path.write_text(s)
