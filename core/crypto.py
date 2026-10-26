"""密码加密工具：AES-CBC / AES-ECB 的纯 Python 实现。"""

from __future__ import annotations

import base64
import random

# 金智 authserver 的 randomString 字符集（原版 encrypt.js 使用同一套）
_IV_ALPHABET = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"


def _rotl8(value: int, shift: int) -> int:
    return ((value << shift) | (value >> (8 - shift))) & 0xFF


def _build_sbox() -> bytes:
    """按 GF(2^8) 逆元 + 仿射变换生成 S 盒，避免手抄 256 项常量。"""
    sbox = [0] * 256
    p = q = 1
    while True:
        # p 乘 3
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        p &= 0xFF
        # q 除 3（即乘 3 的逆元）
        q ^= (q << 1) & 0xFF
        q ^= (q << 2) & 0xFF
        q ^= (q << 4) & 0xFF
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ _rotl8(q, 1) ^ _rotl8(q, 2) ^ _rotl8(q, 3) ^ _rotl8(q, 4)
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    return bytes(sbox)


_SBOX = _build_sbox()


def _xtime(a: int) -> int:
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _mul(a: int, b: int) -> int:
    result = 0
    while b:
        if b & 1:
            result ^= a
        a = _xtime(a)
        b >>= 1
    return result


def _expand_key(key: bytes) -> tuple[list[list[int]], int]:
    nk = len(key) // 4
    if len(key) not in (16, 24, 32):
        raise ValueError("AES 密钥长度必须是 16/24/32 字节")
    nr = nk + 6
    words: list[list[int]] = [list(key[4 * i : 4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        temp = list(words[i - 1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= rcon
            rcon = _xtime(rcon)
        elif nk > 6 and i % nk == 4:
            temp = [_SBOX[b] for b in temp]
        words.append([words[i - nk][j] ^ temp[j] for j in range(4)])
    return words, nr


def _add_round_key(state: list[int], words: list[list[int]], rnd: int) -> None:
    for c in range(4):
        word = words[rnd * 4 + c]
        for r in range(4):
            state[4 * c + r] ^= word[r]


def _sub_bytes(state: list[int]) -> None:
    for i in range(16):
        state[i] = _SBOX[state[i]]


def _shift_rows(state: list[int]) -> None:
    # state 按列存储：state[4*c + r]
    for r in range(1, 4):
        row = [state[4 * c + r] for c in range(4)]
        row = row[r:] + row[:r]
        for c in range(4):
            state[4 * c + r] = row[c]


def _mix_columns(state: list[int]) -> None:
    for c in range(4):
        col = state[4 * c : 4 * c + 4]
        state[4 * c + 0] = _mul(col[0], 2) ^ _mul(col[1], 3) ^ col[2] ^ col[3]
        state[4 * c + 1] = col[0] ^ _mul(col[1], 2) ^ _mul(col[2], 3) ^ col[3]
        state[4 * c + 2] = col[0] ^ col[1] ^ _mul(col[2], 2) ^ _mul(col[3], 3)
        state[4 * c + 3] = _mul(col[0], 3) ^ col[1] ^ col[2] ^ _mul(col[3], 2)


def encrypt_block(block: bytes, key: bytes) -> bytes:
    """加密单个 16 字节分组。"""
    if len(block) != 16:
        raise ValueError("AES 分组长度必须是 16 字节")
    words, nr = _expand_key(key)
    state = list(block)
    _add_round_key(state, words, 0)
    for rnd in range(1, nr):
        _sub_bytes(state)
        _shift_rows(state)
        _mix_columns(state)
        _add_round_key(state, words, rnd)
    _sub_bytes(state)
    _shift_rows(state)
    _add_round_key(state, words, nr)
    return bytes(state)


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad = block_size - len(data) % block_size
    return data + bytes([pad]) * pad


def aes_cbc_encrypt(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-CBC 加密（PKCS#7 填充），不做 base64。"""
    if len(iv) != 16:
        raise ValueError("IV 必须是 16 字节")
    padded = _pkcs7_pad(plaintext)
    out = bytearray()
    prev = iv
    for i in range(0, len(padded), 16):
        block = bytes(a ^ b for a, b in zip(padded[i : i + 16], prev))
        prev = encrypt_block(block, key)
        out += prev
    return bytes(out)


def encrypt_password(password: str, salt: str) -> str:
    """AES-CBC 版本的密码加密（16 位随机 iv 作为前缀）。"""
    if not salt:
        raise ValueError("salt 不能为空")
    key = salt.encode("utf-8")
    iv = "".join(random.choice(_IV_ALPHABET) for _ in range(16))
    cipher = aes_cbc_encrypt(password.encode("utf-8"), key, iv.encode("utf-8"))
    return iv + base64.b64encode(cipher).decode("ascii")


def aes_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """AES-ECB + PKCS#7，用于新版 CAS 登录页（CryptoJS AES/ECB/Pkcs7）。"""
    padded = _pkcs7_pad(plaintext)
    return b"".join(
        encrypt_block(padded[i : i + 16], key) for i in range(0, len(padded), 16)
    )


def encrypt_cas_password(password: str, croypto_b64: str) -> str:
    """AES-ECB 版本的密码加密，key 为 base64 解码后的字符串。"""
    raw_key = base64.b64decode(croypto_b64)
    cipher = aes_ecb_encrypt(password.encode("utf-8"), raw_key)
    return base64.b64encode(cipher).decode("ascii")


def _self_test() -> None:
    # FIPS-197 附录 C 示例
    key = bytes(range(16))
    plain = bytes.fromhex("00112233445566778899aabbccddeeff")
    got = encrypt_block(plain, key)
    assert got.hex() == "69c4e0d86a7b0430d8cdb78070b4c55a", got.hex()
    assert _SBOX[0x00] == 0x63 and _SBOX[0x01] == 0x7C
    token = encrypt_password("123456", "a" * 16)
    assert len(token) == 16 + 24, token
    # AES-ECB：分组结果应与单块加密一致，且 16 字节明文被补齐成 32 字节
    ecb = aes_ecb_encrypt(plain, key)
    assert ecb[:16] == encrypt_block(plain, key)
    assert len(ecb) == 32


if __name__ == "__main__":
    _self_test()
    print("crypto self-test OK")
