#Run the following command before running this script
#pip install azure-keyvault-keys azure-identity

import os
import getpass
from azure.identity import ClientSecretCredential
from azure.keyvault.keys import KeyClient
from azure.keyvault.keys.crypto import CryptographyClient, EncryptionAlgorithm

TENANT_ID=input("Enter TenantID: ")
CLIENT_ID=input("Enter ClientID: ")
CLIENT_SECRET=getpass.getpass(prompt='Enter Client Secret(HIDDEN): ')
VAULT_URL=input("Enter Vault URL: ")
KEY_NAME=input("Enter Key Name: ")

credential = ClientSecretCredential(
    tenant_id=TENANT_ID,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
)

try:
    key_client = KeyClient(
        vault_url=VAULT_URL,
        credential=credential
    )
except Exception as e:
    raise e


arbitrary_string_as_bytes = b'This is my string'

try:
    key = key_client.get_key(name=KEY_NAME)
except Exception as e:
    raise e

crypto_client = CryptographyClient(key, credential=credential)

print(f"Encrypting string {arbitrary_string_as_bytes}")
encrypted_string = crypto_client.encrypt(
    EncryptionAlgorithm.rsa_oaep_256,
    arbitrary_string_as_bytes
)

print('-------')
print(f"Encrypted String Object: {encrypted_string}")
print(f"Encrypted String Algo: {encrypted_string.algorithm}")
print(f"Encrypted String ciphertext:\n{encrypted_string.ciphertext}")
print('-------')
print(f"Decrypting string from ciphertext:\n{encrypted_string.ciphertext}")

decrypted_string = crypto_client.decrypt(
    encrypted_string.algorithm,
    encrypted_string.ciphertext
)

print(f"Decrypted_string: {decrypted_string.plaintext}")