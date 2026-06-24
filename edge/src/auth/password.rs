//! Password hashing and verification (bcrypt).

use bcrypt::{hash, verify, BcryptError, DEFAULT_COST};

#[derive(Clone, Debug)]
pub enum PasswordCredential {
    Plain(String),
    BcryptHash(String),
}

impl PasswordCredential {
    pub fn from_env_plain(value: String) -> Self {
        Self::Plain(value)
    }

    pub fn from_env_hash(value: String) -> Self {
        Self::BcryptHash(value)
    }

    pub fn verify(&self, candidate: &str) -> Result<bool, BcryptError> {
        match self {
            Self::Plain(expected) => Ok(subtle_constant_time_eq(candidate, expected)),
            Self::BcryptHash(hash) => verify(candidate, hash),
        }
    }
}

pub fn hash_password(password: &str) -> Result<String, BcryptError> {
    hash(password, DEFAULT_COST)
}

fn subtle_constant_time_eq(a: &str, b: &str) -> bool {
    use subtle::ConstantTimeEq;
    a.as_bytes().ct_eq(b.as_bytes()).into()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bcrypt_hash_and_verify() {
        let hashed = hash_password("test-password-1234567890").unwrap();
        assert!(hashed.starts_with("$2"));
        assert!(PasswordCredential::BcryptHash(hashed.clone())
            .verify("test-password-1234567890")
            .unwrap());
        assert!(!PasswordCredential::BcryptHash(hashed)
            .verify("wrong")
            .unwrap());
    }

    #[test]
    fn plain_credential_constant_time_compare() {
        let cred = PasswordCredential::Plain("secret-value-1234567890".into());
        assert!(cred.verify("secret-value-1234567890").unwrap());
        assert!(!cred.verify("wrong").unwrap());
    }
}
