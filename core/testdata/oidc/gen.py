# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# Differential-fixture generator for the Rust OIDC validator port.
#
# Runs the REAL Python validator (core/src/infrastructure/auth/oidc.py from
# the immutable snapshot mounted at /ref) against a local HTTP IdP and records
# PyJWT's verdict for every case with a fixed wall clock and a fixed monotonic
# clock. Run with:
#   docker run --rm --add-host idp.test:127.0.0.1 -v /tmp/kumoss-port/orig/core:/ref:ro \
#     -v $PWD:/w -w /w kumoss-pyref python gen.py
import asyncio
import base64
import binascii
import concurrent.futures
import datetime as _dt
import json
import os
import random
import struct
import sys
import threading
import types
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jwt
import jwt.api_jwk
import jwt.api_jwt
import jwt.jwk_set_cache
import jwt.jwks_client
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed448, ed25519, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from jwt.utils import base64url_decode

warnings.simplefilter("ignore")

OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
os.makedirs(OUT, exist_ok=True)
RNG = random.Random(20261029)

# --------------------------------------------------------------------------
# Clocks: PyJWT reads wall time via datetime.now() in api_jwt and monotonic
# time via time.monotonic() in jwks_client / api_jwk / jwk_set_cache.
# --------------------------------------------------------------------------
CLOCK = {"now": 0.0, "mono": 0.0}


class _FakeDatetime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return _dt.datetime.fromtimestamp(CLOCK["now"], tz)


jwt.api_jwt.datetime = _FakeDatetime
_fake_time = types.SimpleNamespace(
    monotonic=lambda: CLOCK["mono"], time=lambda: CLOCK["now"]
)
jwt.jwks_client.time = _fake_time
jwt.api_jwk.time = _fake_time
jwt.jwk_set_cache.time = _fake_time

# --------------------------------------------------------------------------
# Load the real oidc.py with its imports stubbed (config, pool, exceptions).
# --------------------------------------------------------------------------


def _stub(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


_tc_ns = {}
exec(open("/ref/src/domains/value_objects/token_claims.py").read(), _tc_ns)
TokenClaims = _tc_ns["TokenClaims"]


class ExceptionHandler(Exception):
    def __init__(self, message, error_code):
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class TokenValidationError(ExceptionHandler):
    pass


_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def execute_pool(func):
    async def wrapper(*args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_pool, func, *args)

    return wrapper


for pkg in [
    "src",
    "src.domains",
    "src.infrastructure",
    "src.shared",
    "src.shared.config",
    "src.shared.utils",
]:
    _stub(pkg)
_stub("src.domains.value_objects", TokenClaims=TokenClaims)
_stub("src.infrastructure.exceptions", TokenValidationError=TokenValidationError)
_stub(
    "src.shared.config.system_config",
    system_config=types.SimpleNamespace(
        oidc=types.SimpleNamespace(
            issuer_url="", client_id="", audience="", clock_skew_seconds=60
        )
    ),
)
_stub("src.shared.utils.decorators", execute_pool=execute_pool)
oidc = types.ModuleType("oidc_under_test")
exec(
    compile(open("/ref/src/infrastructure/auth/oidc.py").read(), "oidc.py", "exec"),
    oidc.__dict__,
)
OidcTokenValidator = oidc.OidcTokenValidator

# --------------------------------------------------------------------------
# Local IdP on idp.test:80 (docker --add-host idp.test:127.0.0.1).
# --------------------------------------------------------------------------
BODIES = {}  # id -> bytes
ROUTES = {}  # path -> {"status", "body", "headers"}
COUNTS = {}


def body_id(data: bytes) -> str:
    for k, v in BODIES.items():
        if v == data:
            return k
    k = "b%d" % len(BODIES)
    BODIES[k] = data
    return k


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        COUNTS[self.path] = COUNTS.get(self.path, 0) + 1
        r = ROUTES.get(self.path)
        if r is None:
            r = {"status": 404, "body": body_id(b""), "headers": {}}
        data = BODIES[r["body"]]
        self.send_response(r["status"])
        for k, v in r.get("headers", {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


server = ThreadingHTTPServer(("0.0.0.0", 80), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
ISS = "http://idp.test"
DISCOVERY = "/.well-known/openid-configuration"
NOW = 1800000000.5
CLIENT = "kumoss-web"


def b64u(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def b64u_int(n: int, length=None) -> str:
    if length is None:
        length = max(1, (n.bit_length() + 7) // 8)
    return b64u(n.to_bytes(length, "big")).decode()


def jdump(o) -> bytes:
    return json.dumps(o, separators=(",", ":")).encode()


HASHES = {"256": hashes.SHA256, "384": hashes.SHA384, "512": hashes.SHA512}


def sign(alg, key, msg: bytes) -> bytes:
    h = HASHES[alg[2:]]
    if alg.startswith("RS"):
        return key.sign(msg, padding.PKCS1v15(), h())
    if alg.startswith("PS"):
        return key.sign(
            msg, padding.PSS(mgf=padding.MGF1(h()), salt_length=h().digest_size), h()
        )
    if alg.startswith("ES"):
        der = key.sign(msg, ec.ECDSA(h()))
        r, s = decode_dss_signature(der)
        nb = (key.curve.key_size + 7) // 8
        return r.to_bytes(nb, "big") + s.to_bytes(nb, "big")
    if alg.startswith("HS"):
        import hmac

        return hmac.new(
            key, msg, {"256": "sha256", "384": "sha384", "512": "sha512"}[alg[2:]]
        ).digest()
    if alg == "none":
        return b""
    raise ValueError(alg)


def token(
    payload=None,
    *,
    alg="RS256",
    kid="rsa1",
    key=None,
    header=None,
    extra_header=None,
    raw_header=None,
    raw_payload=None,
    sig=None,
    sig_mut=None,
    sign_alg=None,
):
    if header is None:
        header = {"alg": alg, "typ": "JWT"}
        if kid is not None:
            header["kid"] = kid
    if extra_header:
        header.update(extra_header)
    h = raw_header if raw_header is not None else jdump(header)
    p = (
        raw_payload
        if raw_payload is not None
        else jdump(payload if payload is not None else claims())
    )
    si = b64u(h) + b"." + b64u(p)
    if sig is None:
        sa = sign_alg or alg
        if sa not in (
            "RS256",
            "RS384",
            "RS512",
            "PS256",
            "PS384",
            "PS512",
            "ES256",
            "ES384",
            "ES512",
            "HS256",
            "HS384",
            "HS512",
            "none",
        ):
            sa = "RS256"
        sig = sign(sa, key if key is not None else KEYS["rsa1"], si)
    if sig_mut:
        sig = sig_mut(sig)
    return (si + b"." + b64u(sig)).decode()


DROP = object()


def claims(**over):
    p = {
        "iss": ISS,
        "sub": "user-1",
        "aud": CLIENT,
        "exp": int(NOW) + 300,
        "iat": int(NOW) - 10,
        "email": "alice@example.com",
        "email_verified": True,
        "name": "Alice",
    }
    for k, v in over.items():
        if v is DROP:
            p.pop(k, None)
        else:
            p[k] = v
    return p


# --------------------------------------------------------------------------
# Keys and JWKS
# --------------------------------------------------------------------------
print("generating keys...", flush=True)
KEYS = {}


def rsa_key(bits, e=65537):
    return rsa.generate_private_key(public_exponent=e, key_size=bits)


KEYS["rsa1"] = rsa_key(2048)
KEYS["rsa_other"] = rsa_key(2048)
KEYS["rsa3072"] = rsa_key(3072)
KEYS["rsa4096"] = rsa_key(4096)
KEYS["rsa2049"] = rsa_key(2049)
KEYS["rsa1025"] = rsa_key(1025)
KEYS["rsa1024"] = rsa_key(1024)
KEYS["rsa8192"] = rsa_key(8192)
KEYS["rsa_e3"] = rsa_key(2048, e=3)
KEYS["ec256"] = ec.generate_private_key(ec.SECP256R1())
KEYS["ec384"] = ec.generate_private_key(ec.SECP384R1())
KEYS["ec521"] = ec.generate_private_key(ec.SECP521R1())
KEYS["k1"] = ec.generate_private_key(ec.SECP256K1())
KEYS["ed"] = ed25519.Ed25519PrivateKey.generate()
KEYS["ed448"] = ed448.Ed448PrivateKey.generate()
HMAC_SECRET = b"super-secret-hmac-key-material-0123456789"


def rsa_jwk(name, kid=None, **extra):
    nums = KEYS[name].public_key().public_numbers()
    d = {
        "kty": "RSA",
        "kid": kid or name,
        "use": "sig",
        "n": b64u_int(nums.n),
        "e": b64u_int(nums.e),
    }
    d.update(extra)
    return {k: v for k, v in d.items() if v is not DROP}


def ec_jwk(name, kid=None, **extra):
    d = jwt.algorithms.ECAlgorithm.to_jwk(KEYS[name].public_key(), as_dict=True)
    d.update({"kid": kid or name, "use": "sig"})
    d.update(extra)
    return {k: v for k, v in d.items() if v is not DROP}


ed_jwk = jwt.algorithms.OKPAlgorithm.to_jwk(KEYS["ed"].public_key(), as_dict=True)
ed_jwk.update({"kid": "ed", "use": "sig"})
ed448_jwk = jwt.algorithms.OKPAlgorithm.to_jwk(KEYS["ed448"].public_key(), as_dict=True)
ed448_jwk.update({"kid": "ed448", "use": "sig", "alg": "EdDSA"})

# --- special RSA keys built by hand -------------------------------------------


def is_probable_prime(n, k=40):
    if n < 4:
        return n in (2, 3)
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for _ in range(k):
        a = RNG.randrange(2, n - 2)
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def rand_prime(bits):
    while True:
        c = RNG.getrandbits(bits) | (1 << (bits - 1)) | 1
        if is_probable_prime(c):
            return c


DIGEST_INFO = {
    "256": bytes.fromhex("3031300d060960864801650304020105000420"),
    "384": bytes.fromhex("3041300d060960864801650304020205000430"),
    "512": bytes.fromhex("3051300d060960864801650304020305000440"),
}


def pkcs1_raw_sign(n, d, alg, msg):
    import hashlib

    k = (n.bit_length() + 7) // 8
    h = hashlib.new("sha" + alg[2:], msg).digest()
    t = DIGEST_INFO[alg[2:]] + h
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


# even modulus n = 2*p*q with a "valid" raw signature
p_e, q_e = rand_prime(1024), rand_prime(1023)
n_even = 2 * p_e * q_e
lam = (p_e - 1) * (q_e - 1)
d_even = pow(65537, -1, lam)
# large public exponent (> 64 bits) on a 4096-bit modulus, and on a 2048-bit modulus
p_big, q_big = rand_prime(2048), rand_prime(2048)
n_bige = p_big * q_big
E_BIG = (1 << 65) + 1
while True:
    try:
        d_bige = pow(E_BIG, -1, (p_big - 1) * (q_big - 1))
        break
    except ValueError:
        E_BIG += 2
p_b2, q_b2 = rand_prime(1024), rand_prime(1024)
n_bige2 = p_b2 * q_b2
E_BIG2 = (1 << 65) + 1
while True:
    try:
        d_bige2 = pow(E_BIG2, -1, (p_b2 - 1) * (q_b2 - 1))
        break
    except ValueError:
        E_BIG2 += 2
# e = 2^33 + 1 region (rsa crate default cap is 2^33-1)
E_MID = (1 << 34) + 1
while True:
    try:
        d_mid = pow(E_MID, -1, (p_b2 - 1) * (q_b2 - 1))
        break
    except ValueError:
        E_MID += 2

rsa1_priv = KEYS["rsa1"].private_numbers()
P521 = (1 << 521) - 1


def ec_coords(name):
    n = KEYS[name].public_key().public_numbers()
    return n.x, n.y


x521, y521 = ec_coords("ec521")
x256, y256 = ec_coords("ec256")
ec256_d = KEYS["ec256"].private_numbers().private_value
k1x, k1y = ec_coords("k1")


def junk_b64(s: str) -> str:
    # urlsafe_b64decode (non-validating) drops characters outside the alphabet.
    out = []
    for i, c in enumerate(s):
        out.append(c)
        if i % 7 == 3:
            out.append("!")
    return "".join(out)


def to_std_b64(s: str) -> str:
    return s.replace("-", "+").replace("_", "/")


many_kids = ["m%02d" % i for i in range(17)]

STD_KEYS = [
    rsa_jwk("rsa1", alg="RS256"),
    rsa_jwk("rsa3072"),
    rsa_jwk("rsa4096", use=DROP),
    rsa_jwk("rsa2049"),
    rsa_jwk("rsa1025"),
    rsa_jwk("rsa1024"),
    rsa_jwk("rsa8192"),
    rsa_jwk("rsa_e3"),
    rsa_jwk("rsa1", kid="rsa1-ps", alg="PS256"),
    rsa_jwk("rsa1", kid="rsa1-enc", use="enc"),
    rsa_jwk("rsa1", kid="rsa1-usenull", use=None),
    rsa_jwk("rsa1", kid="rsa1-usesigsp", use="sig "),
    rsa_jwk("rsa1", kid="rsa1-hs", alg="HS256"),
    rsa_jwk("rsa1", kid="rsa1-es", alg="ES256"),
    rsa_jwk("rsa1", kid="rsa1-algint", alg=5),
    rsa_jwk("rsa1", kid="rsa1-algempty", alg=""),
    rsa_jwk("rsa1", kid="rsa1-algemptylist", alg=[]),
    rsa_jwk("rsa1", kid="rsa1-junk", n=junk_b64(rsa_jwk("rsa1")["n"])),
    rsa_jwk(
        "rsa1",
        kid="rsa1-junk4",
        n="!!" + rsa_jwk("rsa1")["n"][:10] + " \n" + rsa_jwk("rsa1")["n"][10:],
    ),
    ec_jwk(
        "ec384",
        kid="ec384-priv",
        d=b64u_int(KEYS["ec384"].private_numbers().private_value, 48),
    ),
    ec_jwk(
        "ec521",
        kid="ec521-priv",
        d=b64u_int(KEYS["ec521"].private_numbers().private_value, 66),
    ),
    rsa_jwk("rsa1", kid="rsa1-std", n=to_std_b64(rsa_jwk("rsa1")["n"]) + "=="),
    rsa_jwk("rsa1", kid="rsa1-nint", n=12345),
    rsa_jwk("rsa1", kid="rsa1-ktylower", kty="rsa"),
    rsa_jwk("rsa1", kid="rsa1-nokty", kty=DROP),
    rsa_jwk("rsa1", kid="rsa1-noe", e=DROP),
    {
        "kty": "RSA",
        "kid": "rsa-e2",
        "n": b64u_int(rsa1_priv.public_numbers.n),
        "e": b64u_int(2),
    },
    {
        "kty": "RSA",
        "kid": "rsa-e1",
        "n": b64u_int(rsa1_priv.public_numbers.n),
        "e": b64u_int(1),
    },
    {
        "kty": "RSA",
        "kid": "rsa-e-even",
        "n": b64u_int(rsa1_priv.public_numbers.n),
        "e": b64u_int(65536),
    },
    {"kty": "RSA", "kid": "rsa-n2", "n": b64u_int(2), "e": b64u_int(3)},
    {"kty": "RSA", "kid": "rsa-even-n", "n": b64u_int(n_even), "e": b64u_int(65537)},
    {
        "kty": "RSA",
        "kid": "rsa-big-e-4096",
        "n": b64u_int(n_bige),
        "e": b64u_int(E_BIG),
    },
    {
        "kty": "RSA",
        "kid": "rsa-big-e-2048",
        "n": b64u_int(n_bige2),
        "e": b64u_int(E_BIG2),
    },
    {
        "kty": "RSA",
        "kid": "rsa-mid-e-2048",
        "n": b64u_int(n_bige2),
        "e": b64u_int(E_MID),
    },
    {
        "kty": "RSA",
        "kid": "rsa-n-leading-zero",
        "n": b64u(
            b"\x00\x00" + rsa1_priv.public_numbers.n.to_bytes(256, "big")
        ).decode(),
        "e": b64u_int(65537),
    },
    # private RSA JWKs (full CRT, d only, inconsistent)
    dict(
        rsa_jwk("rsa1", kid="rsa-priv-full"),
        d=b64u_int(rsa1_priv.d),
        p=b64u_int(rsa1_priv.p),
        q=b64u_int(rsa1_priv.q),
        dp=b64u_int(rsa1_priv.dmp1),
        dq=b64u_int(rsa1_priv.dmq1),
        qi=b64u_int(rsa1_priv.iqmp),
    ),
    dict(rsa_jwk("rsa1", kid="rsa-priv-donly"), d=b64u_int(rsa1_priv.d)),
    dict(
        rsa_jwk("rsa1", kid="rsa-priv-partial"),
        d=b64u_int(rsa1_priv.d),
        p=b64u_int(rsa1_priv.p),
    ),
    dict(rsa_jwk("rsa1", kid="rsa-priv-badd"), d=b64u_int(rsa1_priv.d + 2)),
    dict(rsa_jwk("rsa1", kid="rsa-priv-oth"), d=b64u_int(rsa1_priv.d), oth=[]),
    # EC
    ec_jwk("ec256"),
    ec_jwk("ec384"),
    ec_jwk("ec521"),
    ec_jwk("k1"),
    ec_jwk("ec384", kid="ec384-as-es256", alg="ES256"),
    ec_jwk("ec256", kid="ec256-nocrv", crv=DROP),
    ec_jwk("ec256", kid="ec256-crv-p384", crv="P-384"),
    ec_jwk("ec256", kid="ec256-badpoint", y=b64u_int(y256 ^ 1, 32)),
    ec_jwk("ec256", kid="ec256-short", x=b64u_int(x256 >> 8, 31)),
    ec_jwk("ec256", kid="ec256-xint", x=5),
    ec_jwk("ec256", kid="ec256-noy", y=DROP),
    ec_jwk("ec256", kid="ec256-junk", x=junk_b64(ec_jwk("ec256")["x"])),
    ec_jwk("ec521", kid="ec521-xplusp", x=b64u_int(x521 + P521, 66)),
    ec_jwk("ec521", kid="ec521-yplusp", y=b64u_int(y521 + P521, 66)),
    ec_jwk("ec256", kid="ec256-priv", d=b64u_int(ec256_d, 32)),
    ec_jwk("ec256", kid="ec256-priv-wrong", d=b64u_int((ec256_d + 1) % (2**256), 32)),
    ec_jwk("ec256", kid="ec256-priv-short", d=b64u_int(ec256_d >> 8, 31)),
    ec_jwk("ec256", kid="ec256-alg-rs", alg="RS256"),
    ec_jwk("k1", kid="k1-badpoint", y=b64u_int(k1y ^ 1, 32)),
    ec_jwk(
        "k1", kid="k1-priv", d=b64u_int(KEYS["k1"].private_numbers().private_value, 32)
    ),
    ec_jwk("ec256", kid="ec-crv-bad", crv="P-999"),
    # OKP / oct / misc
    ed_jwk,
    ed448_jwk,
    {"kty": "OKP", "kid": "ed448-noalg", "crv": "Ed448", "x": ed448_jwk["x"]},
    {
        "kty": "OKP",
        "kid": "ed-short",
        "crv": "Ed25519",
        "x": b64u(b"\x01" * 31).decode(),
    },
    {"kty": "OKP", "kid": "okp-nocrv", "x": ed_jwk["x"]},
    {"kty": "oct", "kid": "oct", "use": "sig", "k": b64u(HMAC_SECRET).decode()},
    {"kty": "oct", "kid": "oct-empty", "k": ""},
    {"kty": "oct", "kid": "oct-sshrsa", "k": b64u(b"ssh-rsa AAAA").decode()},
    {"kty": "oct", "kid": "oct-ecdsa", "k": b64u(b"ecdsa-sha2-nistp256 AAAA").decode()},
    {"kty": "foo", "kid": "kty-foo"},
    {"kty": "RSA", "kid": 5, "n": rsa_jwk("rsa1")["n"], "e": "AQAB"},
    {"kty": "RSA", "kid": "", "n": rsa_jwk("rsa1")["n"], "e": "AQAB"},
    {"kty": "RSA", "n": rsa_jwk("rsa1")["n"], "e": "AQAB"},
    "not-a-dict",
    17,
    [],
]


def jwks_body(keys):
    return jdump({"keys": keys})


def discovery_body(jwks_uri="http://idp.test/jwks", **extra):
    d = {"issuer": ISS, "jwks_uri": jwks_uri}
    d.update(extra)
    return jdump(d)


def ok_routes(keys=None, disc=None):
    return {
        DISCOVERY: {
            "status": 200,
            "body": body_id(disc if disc is not None else discovery_body()),
            "headers": {"Content-Type": "application/json"},
        },
        "/jwks": {
            "status": 200,
            "body": body_id(jwks_body(keys if keys is not None else STD_KEYS)),
            "headers": {"Content-Type": "application/json"},
        },
    }


def route(status, body=b"", headers=None):
    return {"status": status, "body": body_id(body), "headers": headers or {}}


# --------------------------------------------------------------------------
# Scenario runner
# --------------------------------------------------------------------------
SCENARIOS = []


def clean_str(s):
    # Lone surrogates cannot cross into Rust strings: map them to U+FFFD and
    # flag it so the Rust side expects the same rendering.
    try:
        s.encode("utf-8")
        return s, False
    except UnicodeEncodeError:
        return "".join("�" if 0xD800 <= ord(c) <= 0xDFFF else c for c in s), True


def claim_out(v):
    if v is None:
        return None
    if isinstance(v, str):
        s, sur = clean_str(v)
        if sur:
            return {"surrogate": s}
        return s
    return {"nonstr": repr(v)}


def run_scenario(name, steps, config=None, routes=None):
    cfg = {"issuer_url": ISS + "/", "client_id": CLIENT, "audience": "", "leeway": 60}
    if config:
        cfg.update(config)
    ROUTES.clear()
    ROUTES.update(routes if routes is not None else ok_routes())
    COUNTS.clear()
    v = OidcTokenValidator(
        cfg["issuer_url"], cfg["client_id"], cfg["audience"], cfg["leeway"]
    )
    out_steps = []
    init_routes = dict(ROUTES)
    for st in steps:
        if "routes" in st:
            ROUTES.clear()
            ROUTES.update(st["routes"])
        CLOCK["now"] = st.get("now", NOW)
        CLOCK["mono"] = st.get("mono", 1000.0)
        try:
            c = asyncio.run(v.validate(st["token"]))
            exp = {
                "ok": {
                    "issuer": claim_out(c.issuer),
                    "subject": claim_out(c.subject),
                    "email": claim_out(c.email),
                    "name": claim_out(c.name),
                    "email_verified": c.email_verified,
                }
            }
        except TokenValidationError as e:
            msg, sur = clean_str(e.message)
            exp = {"err": msg}
            if sur:
                exp["surrogate"] = True
        o = {
            "now": CLOCK["now"],
            "mono": CLOCK["mono"],
            "token": st["token"],
            "expect": exp,
            "requests": dict(COUNTS),
        }
        if "routes" in st:
            o["routes"] = st["routes"]
        if "note" in st:
            o["note"] = st["note"]
        out_steps.append(o)
    SCENARIOS.append(
        {"name": name, "config": cfg, "routes": init_routes, "steps": out_steps}
    )


def case(name, tok, config=None, routes=None, now=NOW, mono=1000.0):
    run_scenario(
        name, [{"token": tok, "now": now, "mono": mono}], config=config, routes=routes
    )


# --------------------------------------------------------------------------
# Token matrix
# --------------------------------------------------------------------------
print("building cases...", flush=True)
K = KEYS
# every allowed alg with matching key
for alg in ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512"]:
    case(f"alg {alg} rsa2048", token(alg=alg))
for alg, kid in [("ES256", "ec256"), ("ES384", "ec384"), ("ES512", "ec521")]:
    case(f"alg {alg}", token(alg=alg, kid=kid, key=K[kid]))
for kid in ["rsa3072", "rsa4096", "rsa2049", "rsa1025", "rsa1024", "rsa8192", "rsa_e3"]:
    for alg in ["RS256", "PS256", "PS512", "RS512"]:
        try:
            t_ = token(alg=alg, kid=kid, key=K[kid])
        except ValueError:
            t_ = token(alg=alg, kid=kid, key=K[kid], sign_alg="PS256")
        case(f"{alg} with {kid}", t_)
# PS token verified by a key published with alg RS256 / the other way round
case("PS256 token, JWK alg RS256", token(alg="PS256", kid="rsa1"))
case("RS256 token, JWK alg PS256", token(alg="RS256", kid="rsa1-ps"))
case("RS256 header signed as PS256", token(alg="RS256", sign_alg="PS256"))
case("PS256 header signed as RS256", token(alg="PS256", sign_alg="RS256"))
case("RS384 header signed as RS256", token(alg="RS384", sign_alg="RS256"))
case(
    "ES384 with P-384 key published as ES256",
    token(alg="ES384", kid="ec384-as-es256", key=K["ec384"]),
)
case(
    "ES256 with P-384 key published as ES256",
    token(alg="ES256", kid="ec384-as-es256", key=K["ec384"], sign_alg="ES384"),
)
# key-type mismatches
case("ES256 header, RSA kid", token(alg="ES256", kid="rsa1", key=K["ec256"]))
case("RS256 header, EC kid", token(alg="RS256", kid="ec256"))
case("PS256 header, EC kid", token(alg="PS256", kid="ec256"))
case("ES256 header, P-384 kid", token(alg="ES256", kid="ec384", key=K["ec256"]))
case("ES384 header, P-256 kid", token(alg="ES384", kid="ec256", key=K["ec384"]))
case("ES512 header, P-256 kid", token(alg="ES512", kid="ec256", key=K["ec521"]))
case("ES256 header, secp256k1 kid", token(alg="ES256", kid="k1", key=K["k1"]))
case("RS256 header, oct kid", token(alg="RS256", kid="oct"))
case("ES256 header, oct kid", token(alg="ES256", kid="oct", key=K["ec256"]))
case("RS256 header, oct ssh-rsa kid", token(alg="RS256", kid="oct-sshrsa"))
case("ES256 header, oct ecdsa kid", token(alg="ES256", kid="oct-ecdsa", key=K["ec256"]))
case("RS256 header, Ed25519 kid", token(alg="RS256", kid="ed"))
case("ES256 header, Ed448 kid", token(alg="ES256", kid="ed448", key=K["ec256"]))
case("RS256 header, Ed448 no-alg kid (skipped)", token(alg="RS256", kid="ed448-noalg"))
case("RS256 header, short Ed25519 kid", token(alg="RS256", kid="ed-short"))
case("RS256 header, OKP without crv", token(alg="RS256", kid="okp-nocrv"))
# disallowed algorithms
case("HS256", token(alg="HS256", key=HMAC_SECRET))
case("HS256 oct kid", token(alg="HS256", kid="oct", key=HMAC_SECRET))
case("none", token(alg="none", sig=b""))
case("none with sig", token(alg="none", sig=b"abc"))
case("ES256K", token(alg="ES256K", kid="k1", key=K["k1"], sign_alg="ES256"))
case("EdDSA", token(alg="EdDSA", kid="ed", sig=K["ed"].sign(b"x")))
case("alg empty", token(alg=""))
case("alg null", token(header={"alg": None, "kid": "rsa1"}))
case("alg missing", token(header={"kid": "rsa1"}))
case("alg list", token(header={"alg": ["RS256"], "kid": "rsa1"}))
case("alg lowercase", token(alg="rs256"))
case("alg ES521", token(alg="ES521", kid="ec521", key=K["ec521"], sign_alg="ES512"))
case("alg int", token(header={"alg": 256, "kid": "rsa1"}))

# time claims
case("valid baseline", token())
case("expired", token(claims(exp=int(NOW) - 300)))
case("expired within leeway", token(claims(exp=int(NOW) - 30)))
case("exp boundary expired", token(claims(exp=int(NOW) - 60)))
case("exp boundary valid", token(claims(exp=int(NOW) - 59)))
case(
    "exp boundary int-now expired",
    token(claims(exp=int(NOW) - 60)),
    now=float(int(NOW)),
)
case(
    "exp boundary int-now valid", token(claims(exp=int(NOW) - 59)), now=float(int(NOW))
)
case("leeway 0 exp boundary", token(claims(exp=int(NOW))), config={"leeway": 0})
case("leeway 0 exp +1", token(claims(exp=int(NOW) + 1)), config={"leeway": 0})
case("leeway negative", token(claims(exp=int(NOW) + 30)), config={"leeway": -60})
case("leeway huge", token(claims(exp=1)), config={"leeway": 10**12})
case("nbf in leeway", token(claims(nbf=int(NOW) + 30)))
case("nbf beyond leeway", token(claims(nbf=int(NOW) + 120)))
case("nbf boundary ok", token(claims(nbf=int(NOW) + 60)))
case("nbf boundary bad", token(claims(nbf=int(NOW) + 61)))
case("iat in leeway", token(claims(iat=int(NOW) + 30)))
case("iat beyond leeway", token(claims(iat=int(NOW) + 120)))
case("iat boundary int-now ok", token(claims(iat=int(NOW) + 60)), now=float(int(NOW)))
case("iat boundary int-now bad", token(claims(iat=int(NOW) + 61)), now=float(int(NOW)))
case("iat and nbf bad", token(claims(iat=int(NOW) + 120, nbf=int(NOW) + 120)))
case("expired and iat future", token(claims(exp=1, iat=int(NOW) + 120)))
case("missing exp", token(claims(exp=DROP)))
case("missing iss", token(claims(iss=DROP)))
case("missing sub", token(claims(sub=DROP)))
case("missing all required", token(claims(sub=DROP, iss=DROP, exp=DROP)))
case("exp null", token(claims(exp=None)))
case("sub null", token(claims(sub=None)))
case("iss null", token(claims(iss=None)))
for label, val in [
    ("str", str(int(NOW) + 300)),
    ("str spaced", "  %d \n" % (int(NOW) + 300)),
    ("str underscores", "1_800_000_300"),
    ("str arabic digits", "١٨٠٠٠٠٠٣٠٠"),
    ("str fullwidth", "１８００００００３００"),
    ("str nbsp", "\xa01800000300"),
    ("str plus", "+1800000300"),
    ("str bad", "abc"),
    ("str float", "1800000300.0"),
    ("str hex", "0x6B49D200"),
    ("str 1c", "\x1c1800000300"),
    ("str empty", ""),
    ("float", float(int(NOW) + 300)),
    ("float frac", int(NOW) - 59.9),
    ("float frac2", int(NOW) - 60.5),
    ("true", True),
    ("false", False),
    ("list", []),
    ("dict", {}),
    ("huge", 10**40),
    ("negative", -5),
    ("str double underscore", "1__800000300"),
    ("str trailing underscore", "1800000300_"),
]:
    case(f"exp {label}", token(claims(exp=val)))
    case(f"iat {label}", token(claims(iat=val)))
    case(f"nbf {label}", token(claims(nbf=val)))
for label, raw in [
    ("NaN", b"NaN"),
    ("Infinity", b"Infinity"),
    ("-Infinity", b"-Infinity"),
    ("1e400", b"1e400"),
    ("big int", b"1" + b"0" * 60),
    ("exp form", b"1.8000003e9"),
    ("neg zero", b"-0"),
]:
    for claim in ["exp", "iat", "nbf"]:
        p = (
            jdump(claims()).replace(b"}", b',"%s":%s}' % (claim.encode(), raw))
            if claim != "exp"
            else jdump(claims(exp=DROP)).replace(b"}", b',"exp":%s}' % raw)
        )
        case(f"{claim} raw {label}", token(raw_payload=p))
case("iat null", token(claims(iat=None)))
case("nbf null", token(claims(nbf=None)))

# audience
case("aud api uri", token(claims(aud="api://" + CLIENT)))
case("aud wrong", token(claims(aud="someone-else")))
case("aud list match", token(claims(aud=["x", CLIENT])))
case("aud list nomatch", token(claims(aud=["x", "y"])))
case("aud list nonstr", token(claims(aud=[1, CLIENT])))
case("aud missing", token(claims(aud=DROP)))
case("aud empty str", token(claims(aud="")))
case("aud empty list", token(claims(aud=[])))
case("aud null", token(claims(aud=None)))
case("aud int", token(claims(aud=5)))
case("aud zero", token(claims(aud=0)))
case("aud empty dict", token(claims(aud={})))
case("aud dict", token(claims(aud={"a": 1})))
case("aud true", token(claims(aud=True)))
case("aud false", token(claims(aud=False)))
case("aud case differs", token(claims(aud="Kumoss-Web")))
case(
    "aud NaN", token(raw_payload=jdump(claims(aud=DROP)).replace(b"}", b',"aud":NaN}'))
)
AUDCFG = {"audience": "api://kumoss"}
case("aud override ok", token(claims(aud="api://kumoss")), config=AUDCFG)
case("aud override rejects client id", token(claims(aud=CLIENT)), config=AUDCFG)
case(
    "aud override rejects api client",
    token(claims(aud="api://" + CLIENT)),
    config=AUDCFG,
)
case("aud override list", token(claims(aud=[CLIENT, "api://kumoss"])), config=AUDCFG)
case("client id empty", token(claims(aud="api://")), config={"client_id": ""})
case("client id empty aud empty", token(claims(aud="")), config={"client_id": ""})

# issuer
case("iss trailing slash", token(claims(iss=ISS + "/")))
case("iss double slash", token(claims(iss=ISS + "//")))
case("iss wrong", token(claims(iss="https://evil.test")))
case("iss https", token(claims(iss="https://idp.test")))
case("iss int", token(claims(iss=5)))
case("iss list", token(claims(iss=[ISS])))
case("iss empty", token(claims(iss="")))
case("iss upper", token(claims(iss="HTTP://IDP.TEST")))
case("cfg issuer no slash", token(claims(iss=ISS)), config={"issuer_url": ISS})
case(
    "cfg issuer many slashes",
    token(claims(iss=ISS + "/")),
    config={"issuer_url": ISS + "///"},
)
case("iss wrong and aud wrong", token(claims(iss="x", aud="y")))
case("aud wrong and sub int", token(claims(aud="y", sub=5)))

# sub / jti
case("sub int", token(claims(sub=5)))
case("sub empty", token(claims(sub="")))
case("sub list", token(claims(sub=[])))
case("sub false", token(claims(sub=False)))
case("jti int", token(claims(jti=5)))
case("jti str", token(claims(jti="abc")))
case("jti null", token(claims(jti=None)))

# claims mapping
case("email verified", token())
case("email_verified string true", token(claims(email_verified="true")))
case("email_verified 1", token(claims(email_verified=1)))
case("email_verified false", token(claims(email_verified=False)))
case("email_verified missing", token(claims(email_verified=DROP)))
case(
    "preferred_username fallback",
    token(claims(email=DROP, preferred_username="alice@corp.example")),
)
case(
    "preferred_username fallback verified flag",
    token(claims(email=DROP, preferred_username="p", email_verified=True)),
)
case("email null + pu", token(claims(email=None, preferred_username="p")))
case("email empty + pu verified", token(claims(email="", preferred_username="p")))
case("email empty no pu verified", token(claims(email="")))
case("email false + pu", token(claims(email=False, preferred_username="p")))
case("email false no pu", token(claims(email=False)))
case("email zero pu empty", token(claims(email=0, preferred_username="")))
case("email int", token(claims(email=5)))
case("email list", token(claims(email=["a"])))
case("email empty list pu empty list", token(claims(email=[], preferred_username=[])))
case("pu int", token(claims(email=DROP, preferred_username=5)))
case("pu false", token(claims(email=DROP, preferred_username=False)))
case("name int", token(claims(name=5)))
case("name null", token(claims(name=None)))
case("name empty", token(claims(name="")))
case("name missing", token(claims(name=DROP)))
case("name unicode", token(claims(name="Zoë 名前 \U0001f600")))
case("no optional claims", token(claims(email=DROP, email_verified=DROP, name=DROP)))
case(
    "sub lone surrogate",
    token(raw_payload=jdump(claims(sub=DROP)).replace(b"}", b',"sub":"a\\ud800b"}')),
)
case(
    "email lone surrogate",
    token(
        raw_payload=jdump(claims(email=DROP)).replace(b"}", b',"email":"\\udc00@x"}')
    ),
)
case(
    "name surrogate pair",
    token(
        raw_payload=jdump(claims(name=DROP)).replace(b"}", b',"name":"\\ud83d\\ude00"}')
    ),
)
case(
    "name raw cesu surrogates",
    token(
        raw_payload=jdump(claims(name=DROP)).replace(
            b"}", b',"name":"\xed\xa0\xbd\xed\xb8\x80"}'
        )
    ),
)
case(
    "duplicate sub",
    token(
        raw_payload=jdump(claims(sub=DROP)).replace(
            b"}", b',"sub":"first","sub":"second"}'
        )
    ),
)
case(
    "duplicate exp later expired",
    token(raw_payload=jdump(claims()).replace(b"}", b',"exp":1}')),
)
case(
    "unrelated NaN claim",
    token(
        raw_payload=jdump(claims()).replace(b"}", b',"x":NaN,"y":1e400,"z":-Infinity}')
    ),
)
case(
    "unrelated big int",
    token(raw_payload=jdump(claims()).replace(b"}", b',"x":' + b"9" * 4300 + b"}")),
)
case(
    "unrelated too big int",
    token(raw_payload=jdump(claims()).replace(b"}", b',"x":' + b"9" * 4301 + b"}")),
)
case(
    "deep nesting payload",
    token(
        raw_payload=jdump(claims()).replace(
            b"}", b',"x":' + b"[" * 3000 + b"]" * 3000 + b"}"
        )
    ),
)
case("payload utf-16", token(raw_payload=json.dumps(claims()).encode("utf-16")))
case(
    "payload utf-32-be no bom",
    token(raw_payload=json.dumps(claims()).encode("utf-32-be")),
)
case("payload utf-8 bom", token(raw_payload=b"\xef\xbb\xbf" + jdump(claims())))
case(
    "payload with whitespace",
    token(raw_payload=b" \n" + json.dumps(claims(), indent=2).encode() + b"\r\n"),
)
case("payload list", token(raw_payload=b"[1,2]"))
case("payload invalid json", token(raw_payload=b'{"a":}'))
case("payload trailing comma", token(raw_payload=jdump(claims())[:-1] + b",}"))
case("payload bad utf8", token(raw_payload=b'{"a":"\xff"}'))
case("payload empty", token(raw_payload=b""))
case("payload null", token(raw_payload=b"null"))

# kid handling
case("unknown kid", token(kid="nope"))
case("missing kid", token(kid=None))
case("kid empty", token(kid=""))
case("kid int", token(header={"alg": "RS256", "kid": 5}))
case("kid null", token(header={"alg": "RS256", "kid": None}))
case("kid list", token(header={"alg": "RS256", "kid": ["rsa1"]}))
case("kid use enc", token(kid="rsa1-enc"))
case("kid use null", token(kid="rsa1-usenull"))
case("kid use 'sig '", token(kid="rsa1-usesigsp"))
case("kid no use rsa4096", token(kid="rsa4096", key=K["rsa4096"]))
case("kid lone surrogate", token(raw_header=b'{"alg":"RS256","kid":"x\\ud800y"}'))
case("kid unicode", token(kid="ключ"))
# JWK variants
case("jwk ec384-priv", token(alg="ES384", kid="ec384-priv", key=K["ec384"]))
case("jwk ec521-priv", token(alg="ES512", kid="ec521-priv", key=K["ec521"]))
for kid in [
    "rsa1-junk4",
    "rsa1-hs",
    "rsa1-es",
    "rsa1-algint",
    "rsa1-algempty",
    "rsa1-algemptylist",
    "rsa1-junk",
    "rsa1-std",
    "rsa1-nint",
    "rsa1-ktylower",
    "rsa1-nokty",
    "rsa1-noe",
    "rsa-e2",
    "rsa-e1",
    "rsa-e-even",
    "rsa-n2",
    "rsa-n-leading-zero",
    "rsa-priv-full",
    "rsa-priv-donly",
    "rsa-priv-partial",
    "rsa-priv-badd",
    "rsa-priv-oth",
]:
    case(f"jwk {kid}", token(kid=kid))
case(
    "jwk rsa-even-n",
    token(kid="rsa-even-n", sig=None, key=None, alg="RS256")
    if False
    else token(kid="rsa-even-n", sig=b"\x00"),
)
# even modulus with a mathematically valid signature
_h = jdump({"alg": "RS256", "kid": "rsa-even-n", "typ": "JWT"})
_p = jdump(claims())
_si = b64u(_h) + b"." + b64u(_p)
case(
    "jwk rsa-even-n valid raw sig",
    (_si + b"." + b64u(pkcs1_raw_sign(n_even, d_even, "RS256", _si))).decode(),
)
for kid, n_, d_ in [
    ("rsa-big-e-4096", n_bige, d_bige),
    ("rsa-big-e-2048", n_bige2, d_bige2),
    ("rsa-mid-e-2048", n_bige2, d_mid),
]:
    _h = jdump({"alg": "RS256", "kid": kid, "typ": "JWT"})
    _si = b64u(_h) + b"." + b64u(_p)
    case(
        f"jwk {kid} valid raw sig",
        (_si + b"." + b64u(pkcs1_raw_sign(n_, d_, "RS256", _si))).decode(),
    )
for kid in [
    "ec256-nocrv",
    "ec256-crv-p384",
    "ec256-badpoint",
    "ec256-short",
    "ec256-xint",
    "ec256-noy",
    "ec256-junk",
    "ec256-priv",
    "ec256-priv-wrong",
    "ec256-priv-short",
    "ec256-alg-rs",
    "ec-crv-bad",
]:
    case(f"jwk {kid}", token(alg="ES256", kid=kid, key=K["ec256"]))
for kid in ["ec521-xplusp", "ec521-yplusp"]:
    case(f"jwk {kid}", token(alg="ES512", kid=kid, key=K["ec521"]))
for kid in ["k1-badpoint", "k1-priv"]:
    case(f"jwk {kid}", token(alg="ES256", kid=kid, key=K["k1"]))
case("jwk oct-empty", token(kid="oct-empty"))
case("jwk kty-foo", token(kid="kty-foo"))

# malformed tokens
good = token()
hs, ps_, ss = good.split(".")
for label, t in [
    ("garbage", "not-a-jwt"),
    ("empty", ""),
    ("one dot", "a.b"),
    ("two dots short", "a.b.c"),
    ("dots only", ".."),
    ("four segments", good + ".x"),
    ("five segments", hs + "." + ps_ + ".x." + ss),
    ("header padded", hs + "==." + ps_ + "." + ss),
    ("header plus", hs.replace("e", "+", 1) + "." + ps_ + "." + ss),
    ("header len%4==1", hs + "A." + ps_ + "." + ss),
    ("payload invalid char", hs + "." + ps_[:-1] + "*." + ss),
    ("payload len%4==1", hs + "." + ps_ + "A." + ss),
    ("sig invalid char", hs + "." + ps_ + "." + ss[:-1] + "!"),
    ("sig padded", hs + "." + ps_ + "." + ss + "="),
    ("sig empty", hs + "." + ps_ + "."),
    ("payload empty seg", hs + ".." + ss),
    ("leading space", " " + good),
    ("trailing newline", good + "\n"),
    ("non-ascii", good + "é"),
    ("bearer prefix", "Bearer " + good),
    ("header not json", b64u(b"nope").decode() + "." + ps_ + "." + ss),
    ("header json list", b64u(b"[1]").decode() + "." + ps_ + "." + ss),
    ("header json string", b64u(b'"x"').decode() + "." + ps_ + "." + ss),
    ("header bad utf8", b64u(b'{"alg":"\xff"}').decode() + "." + ps_ + "." + ss),
    (
        "header trailing comma",
        b64u(b'{"alg":"RS256",}').decode() + "." + ps_ + "." + ss,
    ),
    ("header unterminated", b64u(b'{"alg":"RS256').decode() + "." + ps_ + "." + ss),
    (
        "header multiline error",
        b64u(b'{\n"alg":\n  x}').decode() + "." + ps_ + "." + ss,
    ),
    ("header bad escape", b64u(b'{"alg":"\\q"}').decode() + "." + ps_ + "." + ss),
    ("header control char", b64u(b'{"alg":"\x01"}').decode() + "." + ps_ + "." + ss),
    ("header extra data", b64u(b'{"alg":"RS256"} x').decode() + "." + ps_ + "." + ss),
    (
        "header utf16 truncated",
        b64u('{"a":1}'.encode("utf-16-le") + b"A").decode() + "." + ps_ + "." + ss,
    ),
    (
        "header 4301 digits",
        b64u(b'{"x":' + b"1" * 4301 + b"}").decode() + "." + ps_ + "." + ss,
    ),
]:
    case(f"malformed {label}", t)


# non-canonical base64 (trailing bits set)
def _flip_last(seg):
    alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    i = alpha.index(seg[-1])
    return seg[:-1] + alpha[i ^ 1]


case("malformed sig noncanonical", hs + "." + ps_ + "." + _flip_last(ss))
case(
    "malformed header noncanonical",
    _flip_last(hs) + "." + ps_ + "." + ss if len(hs) % 4 else hs + "." + ps_ + "." + ss,
)
case("malformed payload noncanonical", hs + "." + _flip_last(ps_) + "." + ss)
# header variants that parse
case(
    "header utf-16 with bom",
    token(raw_header=json.dumps({"alg": "RS256", "kid": "rsa1"}).encode("utf-16")),
)
case(
    "header utf-16-le no bom",
    token(raw_header=json.dumps({"alg": "RS256", "kid": "rsa1"}).encode("utf-16-le")),
)
case(
    "header utf-8 bom",
    token(raw_header=b"\xef\xbb\xbf" + jdump({"alg": "RS256", "kid": "rsa1"})),
)
case(
    "header duplicate kid",
    token(raw_header=b'{"alg":"RS256","kid":"nope","kid":"rsa1"}'),
)
case(
    "header duplicate alg",
    token(raw_header=b'{"alg":"HS256","kid":"rsa1","alg":"RS256"}'),
)
case(
    "header escaped kid", token(raw_header=b'{"alg":"RS256","kid":"rs\\u0061\\u0031"}')
)
case(
    "header deep nesting",
    token(
        raw_header=b'{"alg":"RS256","kid":"rsa1","x":'
        + b"[" * 2000
        + b"]" * 2000
        + b"}"
    ),
)
case("header no typ", token(header={"alg": "RS256", "kid": "rsa1"}))
case("header typ weird", token(extra_header={"typ": 5}))
# b64 / crit
case("b64 false nonempty payload", token(extra_header={"b64": False}))
case("b64 false empty payload", token(extra_header={"b64": False}, raw_payload=b""))
case(
    "b64 false crit",
    token(extra_header={"b64": False, "crit": ["b64"]}, raw_payload=b""),
)
case("b64 true crit", token(extra_header={"b64": True, "crit": ["b64"]}))
case("b64 zero", token(extra_header={"b64": 0}))
case("crit string", token(extra_header={"crit": "b64"}))
case("crit empty", token(extra_header={"crit": []}))
case("crit int member", token(extra_header={"crit": [1]}))
case("crit unsupported", token(extra_header={"crit": ["exp"]}))
case("crit b64 missing", token(extra_header={"crit": ["b64"]}))
case("crit null", token(extra_header={"crit": None}))
case("kid int and crit bad", token(header={"alg": "RS256", "kid": 5, "crit": []}))
case(
    "kid int and sig bad",
    token(header={"alg": "RS256", "kid": 5}, sig_mut=lambda s: s, sig=b"x").rsplit(
        ".", 1
    )[0]
    + ".A",
)

# signature tampering
case(
    "tampered payload",
    hs + "." + b64u(jdump(claims(sub="mallory"))).decode() + "." + ss,
)
case(
    "tampered signature",
    hs
    + "."
    + ps_
    + "."
    + b64u(
        bytes([base64.urlsafe_b64decode(ss + "==")[0] ^ 1])
        + base64.urlsafe_b64decode(ss + "==")[1:]
    ).decode(),
)
case("wrong key same kid", token(key=K["rsa_other"]))
case("rsa sig truncated", token(sig_mut=lambda s: s[:-1]))
case("rsa sig extended", token(sig_mut=lambda s: s + b"\x00"))
case("rsa sig leading zero added", token(sig_mut=lambda s: b"\x00" + s))
case("rsa sig empty", token(sig=b""))
n_rsa1 = rsa1_priv.public_numbers.n
case(
    "rsa sig plus n",
    token(
        sig_mut=lambda s: (
            (int.from_bytes(s, "big") + n_rsa1)
            .to_bytes(257, "big")
            .lstrip(b"\x00")
            .rjust(256, b"\x00")
            if int.from_bytes(s, "big") + n_rsa1 < 256**256
            else b"\xff" * 256
        )
    ),
)
case("rsa sig all ff", token(sig=b"\xff" * 256))
case("rsa sig equals n", token(sig=n_rsa1.to_bytes(256, "big")))


def find_leading_zero(alg, kid, key, pay_fn):
    for i in range(20000):
        t = token(pay_fn(i), alg=alg, kid=kid, key=key)
        s = base64.urlsafe_b64decode(t.split(".")[2] + "==")
        if s[0] == 0:
            return t, s
    raise RuntimeError("no leading zero")


t_ps, s_ps = find_leading_zero("PS256", "rsa1", K["rsa1"], lambda i: claims())
case("PS256 full sig with leading zero", t_ps)
case(
    "PS256 stripped leading zero",
    t_ps.rsplit(".", 1)[0] + "." + b64u(s_ps[1:]).decode(),
)
t_rs, s_rs = find_leading_zero("RS256", "rsa1", K["rsa1"], lambda i: claims(jti=str(i)))
case("RS256 full sig with leading zero", t_rs)
case(
    "RS256 stripped leading zero",
    t_rs.rsplit(".", 1)[0] + "." + b64u(s_rs[1:]).decode(),
)
t_ps2, s_ps2 = find_leading_zero("PS256", "rsa2049", K["rsa2049"], lambda i: claims())
case(
    "PS256 2049 stripped leading zero",
    t_ps2.rsplit(".", 1)[0] + "." + b64u(s_ps2[1:]).decode(),
)
_both = None
for i in range(0 if os.environ.get("FAST") else 200000):
    t = token(claims(), alg="PS256", kid="rsa1")
    s = base64.urlsafe_b64decode(t.split(".")[2] + "==")
    if s[0] == 0 and s[1] == 0:
        _both = (t, s)
        break
if _both:
    case(
        "PS256 stripped two zeros",
        _both[0].rsplit(".", 1)[0] + "." + b64u(_both[1][2:]).decode(),
    )
    case(
        "PS256 stripped one of two zeros",
        _both[0].rsplit(".", 1)[0] + "." + b64u(_both[1][1:]).decode(),
    )

# ECDSA malleability / encoding
N256 = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
N384 = int(
    "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFC7634D81F4372DDF581A0DB248B0A77AECEC196ACCC52973",
    16,
)
N521 = int(
    "01FF"
    + "FFFFFFFF" * 7
    + "FFFFFFFA"
    + "51868783BF2F966B7FCC0148F709A5D03BB5C9B8899C47AEBB6FB71E91386409",
    16,
)
for alg, kid, nb, N in [
    ("ES256", "ec256", 32, N256),
    ("ES384", "ec384", 48, N384),
    ("ES512", "ec521", 66, N521),
]:
    t = token(alg=alg, kid=kid, key=K[kid])
    sig = base64.urlsafe_b64decode(t.split(".")[2] + "==")
    r, s = int.from_bytes(sig[:nb], "big"), int.from_bytes(sig[nb:], "big")
    head = t.rsplit(".", 1)[0]

    def mk(r_, s_):
        return (
            head + "." + b64u(r_.to_bytes(nb, "big") + s_.to_bytes(nb, "big")).decode()
        )

    case(f"{alg} high-s", mk(r, N - s))
    case(f"{alg} r zero", mk(0, s))
    case(f"{alg} s zero", mk(r, 0))
    case(f"{alg} r plus n", mk(r + N, s) if r + N < 256**nb else mk(N, s))
    case(f"{alg} s equals n", mk(r, N))
    case(f"{alg} sig short", head + "." + b64u(sig[:-1]).decode())
    case(f"{alg} sig long", head + "." + b64u(sig + b"\x00").decode())
    case(
        f"{alg} der sig",
        head
        + "."
        + b64u(K[kid].sign(head.encode(), ec.ECDSA(HASHES[alg[2:]]()))).decode(),
    )
    case(f"{alg} swapped rs", mk(s, r))

# --------------------------------------------------------------------------
# Discovery / JWKS failures
# --------------------------------------------------------------------------
GOOD = token()
JW = ok_routes()["/jwks"]
for label, r in [
    ("404", route(404, b"nope")),
    ("500", route(500)),
    ("503", route(503)),
    ("302 location", route(302, b"", {"Location": "http://idp.test/elsewhere"})),
    ("301 no location", route(301)),
    ("304", route(304)),
    ("300 location", route(300, b"", {"Location": "/x"})),
    ("invalid json", route(200, b"<html>")),
    ("empty body", route(200, b"")),
    ("json list", route(200, b"[]")),
    ("json string", route(200, b'"x"')),
    ("json int", route(200, b"5")),
    ("json null", route(200, b"null")),
    ("json float", route(200, b"1.5")),
    ("json true", route(200, b"true")),
    ("missing jwks_uri", route(200, b'{"issuer":"x"}')),
    ("jwks_uri null", route(200, b'{"jwks_uri":null}')),
    ("jwks_uri int", route(200, b'{"jwks_uri":5}')),
    ("jwks_uri zero", route(200, b'{"jwks_uri":0}')),
    ("jwks_uri list", route(200, b'{"jwks_uri":["a"]}')),
    ("jwks_uri empty list", route(200, b'{"jwks_uri":[]}')),
    ("jwks_uri true", route(200, b'{"jwks_uri":true}')),
    ("jwks_uri false", route(200, b'{"jwks_uri":false}')),
    ("jwks_uri dict", route(200, b'{"jwks_uri":{"a":1}}')),
    ("jwks_uri float", route(200, b'{"jwks_uri":2.5}')),
    ("jwks_uri ftp", route(200, b'{"jwks_uri":"ftp://idp.test/jwks"}')),
    ("jwks_uri empty", route(200, b'{"jwks_uri":""}')),
    ("jwks_uri relative", route(200, b'{"jwks_uri":"/jwks"}')),
    ("jwks_uri upper scheme", route(200, b'{"jwks_uri":"HTTP://idp.test/jwks"}')),
    ("jwks_uri file", route(200, b'{"jwks_uri":"file:///etc/passwd"}')),
    ("jwks_uri weird scheme", route(200, b'{"jwks_uri":"Ht+tp://idp.test/jwks"}')),
    (
        "discovery utf-16",
        route(200, json.dumps({"jwks_uri": "http://idp.test/jwks"}).encode("utf-16")),
    ),
    ("discovery bad utf8", route(200, b'{"jwks_uri":"\xff"}')),
    ("discovery 201", route(201, discovery_body())),
    ("discovery 204", route(204)),
]:
    case(f"discovery {label}", GOOD, routes={DISCOVERY: r, "/jwks": JW})
case("discovery refused", GOOD, config={"issuer_url": "http://127.0.0.1:1"})
case("discovery no scheme", GOOD, config={"issuer_url": "idp.test"})
case("discovery ftp scheme", GOOD, config={"issuer_url": "ftp://idp.test"})
case(
    "jwks refused",
    GOOD,
    routes={
        DISCOVERY: route(200, discovery_body("http://127.0.0.1:1/jwks")),
        "/jwks": JW,
    },
)

DOK = route(200, discovery_body())
for label, r in [
    ("404", route(404, b"nope")),
    ("500", route(500)),
    ("302", route(302, b"", {"Location": "http://idp.test/x"})),
    ("invalid json", route(200, b"<html>")),
    ("empty body", route(200, b"")),
    ("json list", route(200, b"[]")),
    ("json null", route(200, b"null")),
    ("empty object", route(200, b"{}")),
    ("keys empty", route(200, b'{"keys":[]}')),
    ("keys null", route(200, b'{"keys":null}')),
    ("keys string", route(200, b'{"keys":"x"}')),
    ("keys dict", route(200, b'{"keys":{"a":1}}')),
    ("keys non dicts", route(200, b'{"keys":[1,"a",null]}')),
    (
        "keys unusable",
        route(200, jwks_body([{"kty": "RSA"}, {"kty": "foo", "kid": "x"}])),
    ),
    (
        "keys without kid",
        route(
            200, jwks_body([{k: v for k, v in rsa_jwk("rsa1").items() if k != "kid"}])
        ),
    ),
    ("keys all enc", route(200, jwks_body([rsa_jwk("rsa1", use="enc")]))),
    ("keys kid int only", route(200, jwks_body([rsa_jwk("rsa1", kid=7)]))),
    (
        "jwk alg none",
        route(200, jwks_body([rsa_jwk("rsa1"), rsa_jwk("rsa1", kid="z", alg="none")])),
    ),
    (
        "jwk alg list",
        route(
            200, jwks_body([rsa_jwk("rsa1"), rsa_jwk("rsa1", kid="z", alg=["RS256"])])
        ),
    ),
    (
        "jwk alg dict",
        route(
            200, jwks_body([rsa_jwk("rsa1"), rsa_jwk("rsa1", kid="z", alg={"a": 1})])
        ),
    ),
    (
        "jwk oct without k",
        route(200, jwks_body([rsa_jwk("rsa1"), {"kty": "oct", "kid": "z"}])),
    ),
    (
        "jwk oct k int",
        route(200, jwks_body([rsa_jwk("rsa1"), {"kty": "oct", "kid": "z", "k": 5}])),
    ),
    (
        "jwks utf-16",
        route(200, json.dumps({"keys": [rsa_jwk("rsa1")]}).encode("utf-16")),
    ),
    ("jwks 4301 digit", route(200, b'{"x":' + b"1" * 4301 + b',"keys":[]}')),
    ("jwks only rsa1", route(200, jwks_body([rsa_jwk("rsa1")]))),
    (
        "jwks keys first dup",
        route(200, b'{"keys":[],"keys":' + jwks_body([rsa_jwk("rsa1")])[8:]),
    ),
]:
    case(f"jwks {label}", GOOD, routes={DISCOVERY: DOK, "/jwks": r})

# --------------------------------------------------------------------------
# Caching / refresh scenarios (multi-step)
# --------------------------------------------------------------------------
KA = rsa_jwk("rsa1", kid="A")
KB = rsa_jwk("rsa_other", kid="B")
KC = rsa_jwk("rsa3072", kid="C")
tA = token(kid="A")
tB = token(kid="B", key=K["rsa_other"])
tC = token(kid="C", key=K["rsa3072"])
R_A = ok_routes([KA])
R_B = ok_routes([KB])
R_AB = ok_routes([KA, KB])
R_C = ok_routes([KC])

run_scenario(
    "cache: repeated token hits key cache",
    [
        {"token": tA, "mono": 0.0},
        {"token": tA, "mono": 10.0},
        {"token": tA, "mono": 100000.0},
    ],
    routes=R_A,
)
run_scenario(
    "cache: rotation honours cooldown then refreshes; old key stays cached",
    [
        {"token": tA, "mono": 0.0},
        {"token": tB, "mono": 10.0, "routes": R_B},
        {"token": tB, "mono": 29.999},
        {"token": tB, "mono": 30.0},
        {"token": tA, "mono": 31.0},
        {"token": tB, "mono": 32.0},
    ],
    routes=R_A,
)
run_scenario(
    "cache: jwk set lifespan expiry",
    [
        {"token": tA, "mono": 0.0},
        {"token": tC, "mono": 300.0, "routes": R_AB},
        {"token": tC, "mono": 300.5},
        {"token": tB, "mono": 300.5},
        {"token": tC, "mono": 331.0, "routes": R_C},
        {"token": tC, "mono": 340.0},
        {"token": tA, "mono": 341.0},
    ],
    routes=R_A,
)
run_scenario(
    "cache: expired set refetched before kid lookup",
    [
        {"token": tB, "mono": 0.0},
        {"token": tA, "mono": 700.0, "routes": R_A},
        {"token": tB, "mono": 701.0},
        {"token": tB, "mono": 2000.0},
    ],
    routes=R_AB,
)

many = [rsa_jwk("rsa1", kid=k) for k in many_kids]
toks = {k: token(kid=k) for k in many_kids}
steps = [{"token": toks[k], "mono": 0.0} for k in many_kids[:16]]
steps += [{"token": toks["m00"], "mono": 1.0}, {"token": toks["m16"], "mono": 2.0}]
steps += [
    {"token": toks["m00"], "mono": 5.0, "routes": ok_routes([KA])},
    {"token": toks["m01"], "mono": 6.0},
    {"token": toks["m16"], "mono": 7.0},
    {"token": toks["m02"], "mono": 8.0},
    {"token": toks["m01"], "mono": 50.0},
]
run_scenario("cache: LRU of 16 signing keys", steps, routes=ok_routes(many))

run_scenario(
    "cache: discovery failure is retried, success cached forever",
    [
        {"token": tA, "mono": 0.0},
        {"token": tA, "mono": 1.0, "routes": R_A},
        {
            "token": tA,
            "mono": 2.0,
            "routes": {DISCOVERY: route(500), "/jwks": R_A["/jwks"]},
        },
        {
            "token": tB,
            "mono": 500.0,
            "routes": {DISCOVERY: route(500), "/jwks": R_AB["/jwks"]},
        },
    ],
    routes={DISCOVERY: route(500), "/jwks": R_A["/jwks"]},
)
run_scenario(
    "cache: bad jwks_uri scheme is retried",
    [
        {"token": tA, "mono": 0.0},
        {"token": tA, "mono": 1.0, "routes": R_A},
    ],
    routes={
        DISCOVERY: route(200, discovery_body("ftp://idp.test/jwks")),
        "/jwks": R_A["/jwks"],
    },
)
run_scenario(
    "cache: jwks failure then recovery",
    [
        {"token": tA, "mono": 0.0},
        {"token": tA, "mono": 1.0, "routes": R_A},
        {
            "token": tA,
            "mono": 2.0,
            "routes": {DISCOVERY: R_A[DISCOVERY], "/jwks": route(500)},
        },
        {"token": tB, "mono": 100.0},
        {"token": tB, "mono": 101.0, "routes": R_AB},
        {
            "token": tC,
            "mono": 120.0,
            "routes": {DISCOVERY: R_A[DISCOVERY], "/jwks": route(500)},
        },
        {"token": tC, "mono": 140.0},
    ],
    routes={DISCOVERY: R_A[DISCOVERY], "/jwks": route(500)},
)
run_scenario(
    "cache: failed fetch does not reset cooldown or cache",
    [
        {"token": tA, "mono": 0.0},
        {
            "token": tB,
            "mono": 400.0,
            "routes": {DISCOVERY: R_A[DISCOVERY], "/jwks": route(503)},
        },
        {"token": tB, "mono": 401.0, "routes": R_AB},
        {"token": tC, "mono": 402.0},
        {"token": tC, "mono": 431.0, "routes": ok_routes([KA, KB, KC])},
    ],
    routes=R_A,
)
run_scenario(
    "cache: missing kid and unusable refresh",
    [
        {"token": token(kid=None), "mono": 0.0},
        {"token": token(kid=None), "mono": 31.0},
        {
            "token": tB,
            "mono": 62.0,
            "routes": {
                DISCOVERY: R_A[DISCOVERY],
                "/jwks": route(200, b'{"keys":[{"kty":"RSA"}]}'),
            },
        },
        {"token": tA, "mono": 63.0},
        {"token": tA, "mono": 400.0},
    ],
    routes=R_A,
)
run_scenario(
    "cache: failed token does not populate key cache",
    [
        {"token": token(kid="A", key=K["rsa_other"]), "mono": 0.0},
        {"token": tA, "mono": 1.0, "routes": R_B},
        {"token": tA, "mono": 100.0},
    ],
    routes=R_A,
)
run_scenario(
    "cache: wall clock moves independently",
    [
        {"token": token(claims(exp=int(NOW) + 100), kid="A"), "mono": 0.0, "now": NOW},
        {
            "token": token(claims(exp=int(NOW) + 100), kid="A"),
            "mono": 1.0,
            "now": NOW + 161,
        },
        {
            "token": token(claims(exp=int(NOW) + 100), kid="A"),
            "mono": 2.0,
            "now": NOW + 159,
        },
    ],
    routes=R_A,
)

with open(os.path.join(OUT, "scenarios.json"), "w") as f:
    json.dump(
        {
            "bodies": {k: base64.b64encode(v).decode() for k, v in BODIES.items()},
            "scenarios": SCENARIOS,
        },
        f,
        indent=1,
    )
print(
    "scenarios:",
    len(SCENARIOS),
    "steps:",
    sum(len(s["steps"]) for s in SCENARIOS),
    flush=True,
)

# --------------------------------------------------------------------------
# Primitive differential fixtures: json.loads(bytes), int(), base64url_decode
# --------------------------------------------------------------------------
CLAMP = 10**36


def canon(v):
    if v is None:
        return "N"
    if v is True:
        return "T"
    if v is False:
        return "F"
    if isinstance(v, int):
        return "I" + str(max(-CLAMP, min(CLAMP, v)))
    if isinstance(v, float):
        if v != v:
            return "Dnan"
        return "D" + struct.pack(">d", v).hex()
    if isinstance(v, str):
        return "S" + ",".join("%x" % ord(c) for c in v)
    if isinstance(v, list):
        return "[" + ";".join(canon(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ";".join(canon(k) + ":" + canon(x) for k, x in v.items()) + "}"
    raise TypeError(type(v))


SEEDS = [
    b'{"alg":"RS256","kid":"abc","typ":"JWT"}',
    b'[1,2.5,-3e2,true,false,null,"x"]',
    b'{"a":{"b":[{}]},"c":""}',
    b' {"k" : "v\\n\\u00e9\\ud83d\\ude00" , "n" : -0.0e-0 } ',
    b'"\\ud800\\udc00\\udbff"',
    b"[NaN,Infinity,-Infinity]",
    b'{"x":1E400,"y":-1e-400,"z":123456789012345678901234567890}',
    b'"caf\xc3\xa9 \xe2\x82\xac \xf0\x9f\x98\x80"',
    b'[[],[[]],{},{"":""}]',
    b'{"a":1,"a":2}',
    b"0",
    b"-0",
    b'"\\"\\\\\\/\\b\\f\\n\\r\\t"',
    b"1.5e+3",
    b"\t\r\n null \t",
]
ALPH = [
    b" ",
    b"\t",
    b"\n",
    b"\r",
    b"{",
    b"}",
    b"[",
    b"]",
    b":",
    b",",
    b'"',
    b"\\",
    b"u",
    b"0",
    b"1",
    b"9",
    b"a",
    b"F",
    b"-",
    b"+",
    b".",
    b"e",
    b"E",
    b"n",
    b"t",
    b"f",
    b"N",
    b"I",
    b"\x00",
    b"\x01",
    b"\x7f",
    b"\xff",
    b"\xc3",
    b"\xa9",
    b"\xed",
    b"\xa0",
    b"\x80",
    b"\xef\xbb\xbf",
    b"\\u",
    b"\\ud800",
    b"\\udc00",
    b"null",
    b"true",
    b"NaN",
    b"Infinity",
    b"-Infinity",
    b"\xf0\x9f",
    b"\xf4\x90\x80\x80",
    b"\xe0\x80\x80",
]


def mutate(b: bytes) -> bytes:
    b = bytearray(b)
    for _ in range(RNG.randint(1, 3)):
        op = RNG.randrange(5)
        pos = RNG.randint(0, len(b))
        if op == 0 and b:
            del b[min(pos, len(b) - 1)]
        elif op == 1:
            b[pos:pos] = RNG.choice(ALPH)
        elif op == 2 and b:
            b[min(pos, len(b) - 1) : min(pos, len(b) - 1) + 1] = RNG.choice(ALPH)
        elif op == 3:
            b = b[:pos]
        else:
            seg = b[pos : pos + RNG.randint(1, 6)]
            b[pos:pos] = seg
    return bytes(b)


def py_json(data: bytes):
    try:
        return {"out": canon(json.loads(data))}
    except RecursionError:
        return {"err": "RecursionError"}
    except (ValueError,) as e:
        return {"err": str(e)}


json_cases = []
inputs = list(SEEDS)
for s in SEEDS:
    for _ in range(60):
        inputs.append(mutate(s))
for _ in range(400):
    inputs.append(bytes(RNG.choice(ALPH)[0] for _ in range(RNG.randint(0, 8))))
for s in SEEDS[:8]:
    txt = s.decode("utf-8", "surrogatepass")
    for enc in [
        "utf-16",
        "utf-16-le",
        "utf-16-be",
        "utf-32",
        "utf-32-le",
        "utf-32-be",
        "utf-8-sig",
    ]:
        try:
            e = txt.encode(enc, "surrogatepass")
        except Exception:
            continue
        inputs.append(e)
        inputs.append(e[:-1])
        inputs.append(e[:-3] if len(e) > 3 else e)
        inputs.append(e + b"\x00")
        for _ in range(8):
            inputs.append(mutate(e))
inputs += [
    b"\x00\x00\xfe\xff\x00\x00\x00{",
    b"\xff\xfe\x00\x00",
    b"\xfe\xff",
    b"\xff\xfe",
    b"\xfe\xff\x00",
    b"\xff\xfe\x00\xd8",
    b"\xff\xfe\x00\xdc\x00\xd8",
    b"\x00\x00\x00\x22\x00\x00\xd8\x00\x00\x00\x00\x22",
    b"\x22\x00\x00\x00\x00\xd8\x00\x00\x22\x00\x00\x00",
    b'"\x00"',
    b"\x00a",
    b"a\x00",
    b"\x00",
    b"\x00\x00\x00",
    b'"\xed\xb0\x80\xed\xa0\x80"',
    b'"\xed\xbf\xbf"',
    b'"\xc2"',
    b'"\xe0\xa0"',
    b'"\xf0\x90\x80"',
    b'"\xf8\x88\x80\x80\x80"',
    b'"\x80"',
    b"1" * 4301,
    b"-" + b"2" * 4301,
    b"[" + b"1" * 4301 + b"]",
    b"1" * 4300 + b".5",
    b"0." + b"1" * 5000,
    b"1e" + b"9" * 5000,
]
seen = set()
for data in inputs:
    if data in seen:
        continue
    seen.add(data)
    r = py_json(data)
    r["in"] = data.hex()
    json_cases.append(r)

int_values = [
    "0",
    "-0",
    "+0",
    "12",
    " 12 ",
    "\t12\n",
    "\x0b12\x0c",
    "1_2",
    "1__2",
    "_12",
    "12_",
    "-_1",
    "+-1",
    "--1",
    "١٢",
    "١_٢",
    "๑๐",
    "１２",
    "\U0001d7ce\U0001d7cf",
    "²",
    "①",
    "\xa012　",
    "\x8512",
    "\x1c12",
    "12\x1f",
    "1 2",
    "",
    " ",
    "_",
    "0x1f",
    "1e3",
    "1.0",
    "12\x00",
    "\x7f1",
    "١٢\x85",
    " 12 ",
    "᠎12",
    "​12",
    "9" * 4300,
    "9" * 4301,
    "1" + "_0" * 4300,
    "-" + "9" * 50,
    "\U0001fbf5",
    "٠" * 3,
    "0" * 5000,
    0,
    5,
    -7,
    10**50,
    -(10**50),
    True,
    False,
    1.9,
    -1.9,
    0.5,
    -0.0,
    1e300,
    -1e300,
    float("nan"),
    float("inf"),
    float("-inf"),
    None,
    [],
    {},
    [1],
    {"a": 1},
    2**63,
    -(2**63) - 1,
]
CHARS = [
    "0",
    "1",
    "5",
    "9",
    " ",
    "_",
    "+",
    "-",
    "\t",
    "\xa0",
    "٣",
    "５",
    "x",
    ".",
    " ",
    "\x1c",
    "\x85",
    "\U0001d7d9",
]
for _ in range(400):
    int_values.append("".join(RNG.choice(CHARS) for _ in range(RNG.randint(0, 7))))
int_cases = []
for v in int_values:
    text = json.dumps(v)
    try:
        out = str(max(-CLAMP, min(CLAMP, int(v))))
    except (ValueError, TypeError, OverflowError):
        out = None
    int_cases.append({"in": text, "out": out})

b64_inputs = [
    "",
    "A",
    "AA",
    "AAA",
    "AAAA",
    "AAAAA",
    "QQ",
    "QQ=",
    "QQ==",
    "QQ===",
    "Q=Q=",
    "=QQ",
    "Q===",
    "QUJD",
    "QUJ",
    "QU",
    "Q",
    "-_-_",
    "+/+/",
    "a b",
    "a\nb==",
    "QQ!!",
    "!!QQ",
    "Q!Q",
    "é",
    "QQé",
    "AB=C",
    "AB==CD",
    "ABC=D",
    "=",
    "==",
    "===",
    "====",
    "A=",
    "A==",
    "AB=",
    "AB=CD==",
    "ABCD=EFG",
    "AQAB",
    "AQAB=",
    "AQA",
    "AQ",
]
B64CH = list("AQgw_-+/=!. \né") + ["ÿ"]
for _ in range(1500):
    b64_inputs.append("".join(RNG.choice(B64CH) for _ in range(RNG.randint(0, 11))))
b64_cases = []

for s in dict.fromkeys(b64_inputs):
    try:
        out = base64url_decode(s).hex()
    except (binascii.Error, ValueError, TypeError):
        out = None
    b64_cases.append({"in": s, "out": out})

with open(os.path.join(OUT, "primitives.json"), "w") as f:
    json.dump({"json": json_cases, "int": int_cases, "b64": b64_cases}, f, indent=0)
print(
    "json cases:",
    len(json_cases),
    "int cases:",
    len(int_cases),
    "b64 cases:",
    len(b64_cases),
)
server.shutdown()
