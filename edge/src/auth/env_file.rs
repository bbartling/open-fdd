//! Parse and generate workspace/auth.env.local with bcrypt password hashes.

use super::password::{hash_password, PasswordCredential};
use rand::RngCore;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

pub fn default_auth_env_path() -> PathBuf {
    std::env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
        .join("auth.env.local")
}

pub fn parse_env_file(content: &str) -> HashMap<String, String> {
    let mut out = HashMap::new();
    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some((k, v)) = line.split_once('=') {
            out.insert(k.trim().to_string(), v.trim().to_string());
        }
    }
    out
}

pub fn load_env_file(path: &Path) -> std::io::Result<HashMap<String, String>> {
    match fs::read_to_string(path) {
        Ok(text) => Ok(parse_env_file(&text)),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(HashMap::new()),
        Err(e) => Err(e),
    }
}

pub fn apply_env_file(path: &Path) {
    if let Ok(map) = load_env_file(path) {
        for (k, v) in map {
            // Workspace auth file wins — docker env_file may mangle bcrypt `$` sequences.
            // Never override OPENFDD_WORKSPACE from auth.env.local (path resolution depends on it).
            if (k.starts_with("OFDD_") || k.starts_with("OPENFDD_")) && k != "OPENFDD_WORKSPACE" {
                std::env::set_var(&k, v);
            } else if std::env::var(&k).is_err() {
                std::env::set_var(&k, v);
            }
        }
    }
}

fn random_secret_hex(bytes: usize) -> String {
    let mut buf = vec![0_u8; bytes];
    rand::thread_rng().fill_bytes(&mut buf);
    hex::encode(buf)
}

const PASSWORD_LENGTH: usize = 14;

fn random_password() -> String {
    const CHARSET: &[u8] = b"ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#%^*_-";
    let mut rng = rand::thread_rng();
    (0..PASSWORD_LENGTH)
        .map(|_| {
            let idx = (rng.next_u32() as usize) % CHARSET.len();
            CHARSET[idx] as char
        })
        .collect()
}

#[derive(Clone, Copy, Debug)]
pub struct RoleSpec {
    pub user_key: &'static str,
    pub hash_key: &'static str,
    pub pass_key: &'static str,
    pub default_user: &'static str,
    pub role: &'static str,
}

pub const ALL_ROLES: [RoleSpec; 4] = [
    RoleSpec {
        user_key: "OFDD_OPERATOR_USER",
        hash_key: "OFDD_OPERATOR_PASSWORD_HASH",
        pass_key: "OFDD_OPERATOR_PASSWORD",
        default_user: "operator",
        role: "operator",
    },
    RoleSpec {
        user_key: "OFDD_INTEGRATOR_USER",
        hash_key: "OFDD_INTEGRATOR_PASSWORD_HASH",
        pass_key: "OFDD_INTEGRATOR_PASSWORD",
        default_user: "integrator",
        role: "integrator",
    },
    RoleSpec {
        user_key: "OFDD_AGENT_USER",
        hash_key: "OFDD_AGENT_PASSWORD_HASH",
        pass_key: "OFDD_AGENT_PASSWORD",
        default_user: "agent",
        role: "agent",
    },
    RoleSpec {
        user_key: "OFDD_ADMIN_USER",
        hash_key: "OFDD_ADMIN_PASSWORD_HASH",
        pass_key: "OFDD_ADMIN_PASSWORD",
        default_user: "admin",
        role: "admin",
    },
];

pub struct GenerateOptions {
    pub path: PathBuf,
    pub force: bool,
    pub show_secrets: bool,
}

pub struct GenerateResult {
    pub created: bool,
    pub path: PathBuf,
    pub contents: String,
    pub plaintext_passwords: HashMap<String, String>,
}

pub struct RotateOptions {
    pub path: PathBuf,
    pub all: bool,
    pub role: Option<String>,
    pub show_secrets: bool,
}

fn hash_or_panic(password: &str) -> String {
    hash_password(password).expect("bcrypt hash")
}

fn read_username(map: &HashMap<String, String>, spec: &RoleSpec) -> String {
    map.get(spec.user_key)
        .cloned()
        .unwrap_or_else(|| spec.default_user.to_string())
}

pub fn generate_auth_env(opts: &GenerateOptions) -> std::io::Result<GenerateResult> {
    if opts.path.exists() && !opts.force {
        let contents = fs::read_to_string(&opts.path)?;
        return Ok(GenerateResult {
            created: false,
            path: opts.path.clone(),
            contents,
            plaintext_passwords: HashMap::new(),
        });
    }

    if let Some(parent) = opts.path.parent() {
        fs::create_dir_all(parent)?;
    }

    let existing = load_env_file(&opts.path).unwrap_or_default();
    let secret = random_secret_hex(32);
    let operator_pw = random_password();
    let integrator_pw = random_password();
    let agent_pw = random_password();
    let admin_pw = random_password();

    let operator_user = read_username(&existing, &ALL_ROLES[0]);
    let integrator_user = read_username(&existing, &ALL_ROLES[1]);
    let agent_user = read_username(&existing, &ALL_ROLES[2]);
    let admin_user = read_username(&existing, &ALL_ROLES[3]);

    let contents = format!(
        "# Open-FDD edge auth — generated by openfdd_edge (bcrypt hashes only)\n\
         # chmod 600 recommended. Never commit this file.\n\
         OFDD_AUTH_REQUIRED=true\n\
         OFDD_AUTH_SECRET={secret}\n\
         OFDD_OPERATOR_USER={operator_user}\n\
         OFDD_OPERATOR_PASSWORD_HASH={}\n\
         OFDD_INTEGRATOR_USER={integrator_user}\n\
         OFDD_INTEGRATOR_PASSWORD_HASH={}\n\
         OFDD_AGENT_USER={agent_user}\n\
         OFDD_AGENT_PASSWORD_HASH={}\n\
         OFDD_ADMIN_USER={admin_user}\n\
         OFDD_ADMIN_PASSWORD_HASH={}\n\
         OFDD_JWT_TTL_SECONDS=28800\n\
         OPENFDD_AUTH_TTL_SEC=28800\n\
         OFDD_COOKIE_SECURE=false\n",
        hash_or_panic(&operator_pw),
        hash_or_panic(&integrator_pw),
        hash_or_panic(&agent_pw),
        hash_or_panic(&admin_pw),
    );

    fs::write(&opts.path, &contents)?;
    chmod_600_unix(&opts.path);

    let mut plaintext_passwords = HashMap::new();
    plaintext_passwords.insert(operator_user.clone(), operator_pw);
    plaintext_passwords.insert(integrator_user.clone(), integrator_pw);
    plaintext_passwords.insert(agent_user.clone(), agent_pw);
    plaintext_passwords.insert(admin_user, admin_pw);

    Ok(GenerateResult {
        created: true,
        path: opts.path.clone(),
        contents,
        plaintext_passwords,
    })
}

pub fn rotate_auth_env(opts: &RotateOptions) -> std::io::Result<GenerateResult> {
    if !opts.path.exists() {
        return generate_auth_env(&GenerateOptions {
            path: opts.path.clone(),
            force: true,
            show_secrets: opts.show_secrets,
        });
    }

    let backup = format!(
        "{}.bak.{}",
        opts.path.display(),
        chrono::Utc::now().format("%Y%m%dT%H%M%SZ")
    );
    fs::copy(&opts.path, &backup)?;

    let mut map = load_env_file(&opts.path)?;
    let rotate_all = opts.all || opts.role.is_none();
    let mut rotated = HashMap::new();

    for spec in ALL_ROLES {
        if !rotate_all {
            let want = opts.role.as_deref().unwrap_or("");
            if spec.role != want && spec.default_user != want {
                continue;
            }
        }
        let user = read_username(&map, &spec);
        let pw = random_password();
        map.insert(spec.hash_key.to_string(), hash_or_panic(&pw));
        map.remove(spec.pass_key);
        rotated.insert(user, pw);
    }

    if rotate_all {
        map.insert("OFDD_AUTH_SECRET".into(), random_secret_hex(32));
    }

    let mut lines = vec![
        "# Open-FDD edge auth — rotated by openfdd_edge".to_string(),
        format!(
            "OFDD_AUTH_REQUIRED={}",
            map.get("OFDD_AUTH_REQUIRED")
                .cloned()
                .unwrap_or_else(|| "true".into())
        ),
        format!(
            "OFDD_AUTH_SECRET={}",
            map.get("OFDD_AUTH_SECRET")
                .cloned()
                .unwrap_or_else(|| random_secret_hex(32))
        ),
    ];
    for spec in ALL_ROLES {
        let user = read_username(&map, &spec);
        lines.push(format!("{}={}", spec.user_key, user));
        if let Some(hash) = map.get(spec.hash_key) {
            lines.push(format!("{}={}", spec.hash_key, hash));
        }
    }
    lines.push(format!(
        "OFDD_JWT_TTL_SECONDS={}",
        map.get("OFDD_JWT_TTL_SECONDS")
            .cloned()
            .unwrap_or_else(|| "28800".into())
    ));
    lines.push("OPENFDD_AUTH_TTL_SEC=28800".into());
    lines.push(format!(
        "OFDD_COOKIE_SECURE={}",
        map.get("OFDD_COOKIE_SECURE")
            .cloned()
            .unwrap_or_else(|| "false".into())
    ));

    let contents = lines.join("\n") + "\n";
    fs::write(&opts.path, &contents)?;
    chmod_600_unix(&opts.path);

    Ok(GenerateResult {
        created: true,
        path: opts.path.clone(),
        contents,
        plaintext_passwords: rotated,
    })
}

pub fn print_generated_credentials(passwords: &HashMap<String, String>, show_secrets: bool) {
    if passwords.is_empty() {
        return;
    }
    if !show_secrets {
        eprintln!("New credentials generated. Re-run with --show-secrets to print once.");
        return;
    }
    eprintln!("SAVE THESE CREDENTIALS NOW — plaintext is not stored in auth.env.local:");
    for (user, pw) in passwords {
        eprintln!("  {user}: {pw}");
    }
}

/// Write one-time credential handoff file next to auth.env.local (lab bootstrap only).
pub fn write_bootstrap_credentials_once(
    auth_path: &Path,
    passwords: &HashMap<String, String>,
) -> std::io::Result<Option<PathBuf>> {
    if passwords.is_empty() {
        return Ok(None);
    }
    let workspace = auth_path.parent().unwrap_or_else(|| Path::new("workspace"));
    let handoff = workspace.join("bootstrap_credentials.once.txt");
    let mut lines = vec![
        "# Open-FDD one-time bootstrap credentials — DELETE after saving to your password manager."
            .to_string(),
        "# Do NOT commit this file. Do NOT paste bcrypt hashes from auth.env.local as passwords."
            .to_string(),
        format!("# Generated: {}", chrono::Utc::now().to_rfc3339()),
        String::new(),
    ];
    for (user, pw) in passwords {
        lines.push(format!("{user}: {pw}"));
    }
    lines.push(String::new());
    lines.push("# After saving passwords, delete this file:".to_string());
    lines.push("#   rm workspace/bootstrap_credentials.once.txt".to_string());
    fs::write(&handoff, lines.join("\n"))?;
    chmod_600_unix(&handoff);
    Ok(Some(handoff))
}

pub fn chmod_600_unix(path: &Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(meta) = fs::metadata(path) {
            let mut perms = meta.permissions();
            perms.set_mode(0o600);
            let _ = fs::set_permissions(path, perms);
        }
    }
}

pub fn redact_env_line(key: &str, value: &str) -> String {
    if key.contains("SECRET")
        || key.contains("PASSWORD")
        || key.contains("TOKEN")
        || key.contains("HASH")
    {
        format!("{key}=***REDACTED***")
    } else {
        format!("{key}={value}")
    }
}

pub fn print_env_summary(contents: &str, show_secrets: bool) {
    for line in contents.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some((k, v)) = line.split_once('=') {
            if show_secrets {
                println!("{k}={v}");
            } else {
                println!("{}", redact_env_line(k, v));
            }
        }
    }
}

pub fn load_password_credential(
    map: &HashMap<String, String>,
    hash_key: &str,
    pass_key: &str,
) -> Option<PasswordCredential> {
    if let Some(hash) = map.get(hash_key) {
        if !hash.is_empty() {
            return Some(PasswordCredential::from_env_hash(hash.clone()));
        }
    }
    map.get(pass_key)
        .cloned()
        .map(PasswordCredential::from_env_plain)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_auth_path() -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "openfdd-auth-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = fs::create_dir_all(&dir);
        dir.join("auth.env.local")
    }

    #[test]
    fn generated_passwords_are_fourteen_chars() {
        let path = temp_auth_path();
        let _ = fs::remove_file(&path);
        let result = generate_auth_env(&GenerateOptions {
            path: path.clone(),
            force: true,
            show_secrets: false,
        })
        .unwrap();
        for pw in result.plaintext_passwords.values() {
            assert_eq!(pw.len(), PASSWORD_LENGTH);
        }
        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn generated_file_uses_hashes_not_plaintext() {
        let path = temp_auth_path();
        let _ = fs::remove_file(&path);
        let result = generate_auth_env(&GenerateOptions {
            path: path.clone(),
            force: true,
            show_secrets: false,
        })
        .unwrap();
        assert!(result.created);
        assert!(result.contents.contains("OFDD_INTEGRATOR_PASSWORD_HASH=$2"));
        assert!(!result.contents.contains("OFDD_INTEGRATOR_PASSWORD="));
        assert_eq!(result.plaintext_passwords.len(), 4);
        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn existing_file_preserved_without_force() {
        let path = temp_auth_path();
        fs::write(&path, "OFDD_AUTH_SECRET=keep-me\n").unwrap();
        let result = generate_auth_env(&GenerateOptions {
            path: path.clone(),
            force: false,
            show_secrets: false,
        })
        .unwrap();
        assert!(!result.created);
        assert!(result.contents.contains("keep-me"));
        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn rotate_changes_selected_role() {
        let path = temp_auth_path();
        generate_auth_env(&GenerateOptions {
            path: path.clone(),
            force: true,
            show_secrets: true,
        })
        .unwrap();
        let before = fs::read_to_string(&path).unwrap();
        let result = rotate_auth_env(&RotateOptions {
            path: path.clone(),
            all: false,
            role: Some("agent".into()),
            show_secrets: true,
        })
        .unwrap();
        assert!(result.created);
        let after = fs::read_to_string(&path).unwrap();
        assert_ne!(before, after);
        assert!(after.contains("OFDD_AGENT_PASSWORD_HASH=$2"));
        let _ = fs::remove_dir_all(path.parent().unwrap());
    }
}
