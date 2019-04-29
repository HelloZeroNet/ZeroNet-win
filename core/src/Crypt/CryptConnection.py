import sys
import logging
import os
import ssl
import hashlib
import random

from Config import config
from util import SslPatch
from util import helper


class CryptConnectionManager:
    def __init__(self):
        # OpenSSL params
        if sys.platform.startswith("win"):
            self.openssl_bin = "src\\lib\\opensslVerify\\openssl.exe"
        else:
            self.openssl_bin = "openssl"
        self.openssl_env = {"OPENSSL_CONF": "src/lib/opensslVerify/openssl.cnf"}

        self.crypt_supported = []  # Supported cryptos

        self.cacert_pem = config.data_dir + "/cacert-rsa.pem"
        self.cakey_pem = config.data_dir + "/cakey-rsa.pem"
        self.cert_pem = config.data_dir + "/cert-rsa.pem"
        self.cert_csr = config.data_dir + "/cert-rsa.csr"
        self.key_pem = config.data_dir + "/key-rsa.pem"

    # Select crypt that supported by both sides
    # Return: Name of the crypto
    def selectCrypt(self, client_supported):
        for crypt in self.crypt_supported:
            if crypt in client_supported:
                return crypt
        return False

    # Wrap socket for crypt
    # Return: wrapped socket
    def wrapSocket(self, sock, crypt, server=False, cert_pin=None):
        if crypt == "tls-rsa":
            ciphers = "ECDHE-RSA-CHACHA20-POLY1305:ECDHE-RSA-AES128-GCM-SHA256:AES128-SHA256:AES256-SHA:"
            ciphers += "!aNULL:!eNULL:!EXPORT:!DSS:!DES:!RC4:!3DES:!MD5:!PSK"
            if server:
                sock_wrapped = ssl.wrap_socket(
                    sock, server_side=server, keyfile=self.key_pem,
                    certfile=self.cert_pem, ciphers=ciphers
                )
            else:
                sock_wrapped = ssl.wrap_socket(sock, ciphers=ciphers)
            if cert_pin:
                cert_hash = hashlib.sha256(sock_wrapped.getpeercert(True)).hexdigest()
                assert cert_hash == cert_pin, "Socket certificate does not match (%s != %s)" % (cert_hash, cert_pin)
            return sock_wrapped
        else:
            return sock

    def removeCerts(self):
        if config.keep_ssl_cert:
            return False
        for file_name in ["cert-rsa.pem", "key-rsa.pem", "cacert-rsa.pem", "cakey-rsa.pem", "cacert-rsa.srl", "cert-rsa.csr"]:
            file_path = "%s/%s" % (config.data_dir, file_name)
            if os.path.isfile(file_path):
                os.unlink(file_path)

    # Load and create cert files is necessary
    def loadCerts(self):
        if config.disable_encryption:
            return False

        if self.createSslRsaCert() and "tls-rsa" not in self.crypt_supported:
            self.crypt_supported.append("tls-rsa")

    # Try to create RSA server cert + sign for connection encryption
    # Return: True on success
    def createSslRsaCert(self):
        casubjects = [
            "/C=US/O=Amazon/OU=Server CA 1B/CN=Amazon",
            "/C=US/O=Let's Encrypt/CN=Let's Encrypt Authority X3",
            "/C=US/O=DigiCert Inc/OU=www.digicert.com/CN=DigiCert SHA2 High Assurance Server CA",
            "/C=GB/ST=Greater Manchester/L=Salford/O=COMODO CA Limited/CN=COMODO RSA Domain Validation Secure Server CA"
        ]
        fakedomains = [
            "yahoo.com", "amazon.com", "live.com", "microsoft.com", "mail.ru", "csdn.net", "bing.com",
            "amazon.co.jp", "office.com", "imdb.com", "msn.com", "samsung.com", "huawei.com", "ztedevices.com",
            "godaddy.com", "w3.org", "gravatar.com", "creativecommons.org", "hatena.ne.jp",
            "adobe.com", "opera.com", "apache.org", "rambler.ru", "one.com", "nationalgeographic.com",
            "networksolutions.com", "php.net", "python.org", "phoca.cz", "debian.org", "ubuntu.com",
            "nazwa.pl", "symantec.com"
        ]
        self.openssl_env['CN'] = random.choice(fakedomains)

        if os.path.isfile(self.cert_pem) and os.path.isfile(self.key_pem):
            return True  # Files already exits

        import subprocess
        # Generate CAcert and CAkey
        cmd = "%s req -new -newkey rsa:2048 -days 3650 -nodes -x509 -subj %s -keyout %s -out %s -batch -config %s" % helper.shellquote(
            self.openssl_bin,
            random.choice(casubjects),
            self.cakey_pem,
            self.cacert_pem,
            self.openssl_env["OPENSSL_CONF"],
        )
        proc = subprocess.Popen(
            cmd.encode(sys.getfilesystemencoding()),
            shell=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, env=self.openssl_env
        )
        back = proc.stdout.read().strip()
        proc.wait()
        logging.debug("Generating RSA CAcert and CAkey PEM files...%s" % back)

        if not (os.path.isfile(self.cacert_pem) and os.path.isfile(self.cakey_pem)):
            logging.error("RSA ECC SSL CAcert generation failed, CAcert or CAkey files not exist.")
            return False

        # Generate certificate key and signing request
        cmd = "%s req -new -newkey rsa:2048 -keyout %s -out %s -subj %s -sha256 -nodes -batch -config %s" % helper.shellquote(
            self.openssl_bin,
            self.key_pem,
            self.cert_csr,
            "/CN=" + self.openssl_env['CN'],
            self.openssl_env["OPENSSL_CONF"],
        )
        proc = subprocess.Popen(
            cmd.encode(sys.getfilesystemencoding()),
            shell=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, env=self.openssl_env
        )
        back = proc.stdout.read().strip()
        proc.wait()
        logging.debug("Generating certificate key and signing request...%s" % back)

        # Sign request and generate certificate
        cmd = "%s x509 -req -in %s -CA %s -CAkey %s -CAcreateserial -out %s -days 730 -sha256 -extensions x509_ext -extfile %s" % helper.shellquote(
            self.openssl_bin,
            self.cert_csr,
            self.cacert_pem,
            self.cakey_pem,
            self.cert_pem,
            self.openssl_env["OPENSSL_CONF"],
        )
        proc = subprocess.Popen(
            cmd.encode(sys.getfilesystemencoding()),
            shell=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, env=self.openssl_env
        )
        back = proc.stdout.read().strip()
        proc.wait()
        logging.debug("Generating RSA cert...%s" % back)

        if os.path.isfile(self.cert_pem) and os.path.isfile(self.key_pem):
            return True
        else:
            logging.error("RSA ECC SSL cert generation failed, cert or key files not exist.")
            return False


manager = CryptConnectionManager()
