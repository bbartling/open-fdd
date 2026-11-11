"""``sin`` exactly as JavaScript engines (V8's fdlibm port) compute it.

CPython's ``math.sin`` calls the platform libm, which may differ from V8 by 1 ulp on some arguments (and differs between
operating systems). The parity datasets must be bit-identical to the JS generator and across platforms, so the
generator uses this pure-Python port of fdlibm ``sin`` (kernel sin/cos and argument reduction for |x| < ~1.6e6).
"""
from __future__ import annotations

import math
import struct

_S1, _S2, _S3, _S4, _S5, _S6 = (-1.66666666666666324348e-01, 8.33333333332248946124e-03, -1.98412698298579493134e-04,
                                2.75573137070700676789e-06, -2.50507602534068634195e-08, 1.58969099521155010221e-10)
_C1, _C2, _C3, _C4, _C5, _C6 = (4.16666666666666019037e-02, -1.38888888888741095749e-03, 2.48015872894767294178e-05,
                                -2.75573143513906633035e-07, 2.08757232129817482790e-09, -1.13596475577881948265e-11)
_INVPIO2 = 6.36619772367581382433e-01
_PIO2_1 = 1.57079632673412561417e+00
_PIO2_1T = 6.07710050650619224932e-11
_PIO2_2 = 6.07710050630396597660e-11
_PIO2_2T = 2.02226624879595063154e-21
_PIO2_3 = 2.02226624871116645580e-21
_PIO2_3T = 8.47842766036889956997e-32

_pack, _unpack = struct.Struct(">d").pack, struct.Struct(">d").unpack


def _hi(x: float) -> int:
    """High 32 bits of the IEEE-754 double (signed)."""
    return struct.unpack(">i", _pack(x)[:4])[0]


def _from_words(hi: int, lo: int = 0) -> float:
    return _unpack(struct.pack(">II", hi & 0xFFFFFFFF, lo))[0]


def _kernel_sin(x: float, y: float, iy: int) -> float:
    ix = _hi(x) & 0x7FFFFFFF
    if ix < 0x3E400000 and int(x) == 0:
        return x
    z = x * x
    v = z * x
    r = _S2 + z * (_S3 + z * (_S4 + z * (_S5 + z * _S6)))
    if iy == 0:
        return x + v * (_S1 + z * r)
    return x - ((z * (0.5 * y - v * r) - y) - v * _S1)


def _kernel_cos(x: float, y: float) -> float:
    ix = _hi(x) & 0x7FFFFFFF
    if ix < 0x3E400000 and int(x) == 0:
        return 1.0
    z = x * x
    r = z * (_C1 + z * (_C2 + z * (_C3 + z * (_C4 + z * (_C5 + z * _C6)))))
    if ix < 0x3FD33333:
        return 1.0 - (0.5 * z - (z * r - x * y))
    qx = 0.28125 if ix > 0x3FE90000 else _from_words(ix - 0x00200000)
    iz = 0.5 * z - qx
    a = 1.0 - qx
    return a - (iz - (z * r - x * y))


def _rem_pio2(x: float):
    hx = _hi(x)
    ix = hx & 0x7FFFFFFF
    if ix <= 0x3FE921FB:
        return 0, x, 0.0
    if ix < 0x4002D97C:  # |x| < 3pi/4: n = +-1
        if hx > 0:
            z = x - _PIO2_1
            if ix != 0x3FF921FB:
                y0 = z - _PIO2_1T
                return 1, y0, (z - y0) - _PIO2_1T
            z -= _PIO2_2
            y0 = z - _PIO2_2T
            return 1, y0, (z - y0) - _PIO2_2T
        z = x + _PIO2_1
        if ix != 0x3FF921FB:
            y0 = z + _PIO2_1T
            return -1, y0, (z - y0) + _PIO2_1T
        z += _PIO2_2
        y0 = z + _PIO2_2T
        return -1, y0, (z - y0) + _PIO2_2T
    t = abs(x)
    n = int(t * _INVPIO2 + 0.5)
    fn = float(n)
    r = t - fn * _PIO2_1
    w = fn * _PIO2_1T
    j = ix >> 20
    y0 = r - w
    i = j - ((_hi(y0) >> 20) & 0x7FF)
    if i > 16:
        t = r
        w = fn * _PIO2_2
        r = t - w
        w = fn * _PIO2_2T - ((t - r) - w)
        y0 = r - w
        i = j - ((_hi(y0) >> 20) & 0x7FF)
        if i > 49:
            t = r
            w = fn * _PIO2_3
            r = t - w
            w = fn * _PIO2_3T - ((t - r) - w)
            y0 = r - w
    y1 = (r - y0) - w
    if hx < 0:
        return -n, -y0, -y1
    return n, y0, y1


def sin(x: float) -> float:
    ix = _hi(x) & 0x7FFFFFFF
    if ix <= 0x3FE921FB:
        return _kernel_sin(x, 0.0, 0)
    if ix >= 0x7FF00000:
        return math.nan
    if ix > 0x413921FB:  # beyond the medium-size reduction (|x| > ~1.6e6 rad): platform libm
        return math.sin(x)
    n, y0, y1 = _rem_pio2(x)
    k = n & 3
    if k == 0:
        return _kernel_sin(y0, y1, 1)
    if k == 1:
        return _kernel_cos(y0, y1)
    if k == 2:
        return -_kernel_sin(y0, y1, 1)
    return -_kernel_cos(y0, y1)
