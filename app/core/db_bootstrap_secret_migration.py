from secret_store import encrypt_communication_secrets, encrypt_server_secrets


def migrate_plaintext_secrets(conn) -> None:
    encrypted = encrypt_communication_secrets(conn)
    if encrypted:
        print(f"Encrypted {encrypted} communication secret row(s)")
        conn.commit()

    encrypted = encrypt_server_secrets(conn)
    if encrypted:
        print(f"Encrypted {encrypted} server secret row(s)")
        conn.commit()
