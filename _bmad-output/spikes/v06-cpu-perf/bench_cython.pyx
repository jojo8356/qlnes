# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""bench_cython.pyx — Cython-typed mirror of the pure-Python benchmark
workloads. Compiled to a CPython C extension by build_cython.py.

Each workload is the same algorithm as in benchmark_runtimes.py, but with:
- C-typed locals (cdef int/double) so loops compile to native C
- bint where appropriate
- minimal Python-object boxing in inner loops

This is the "fair Cython" version: a developer who reaches for Cython
would naturally reach for these annotations. We do NOT use memoryviews
or nogil here — the goal is to measure what an idiomatic Cython port
of the same code produces, not the absolute Cython ceiling.
"""
from libc.math cimport sqrt
from libc.stdint cimport uint32_t


cpdef long fib_recursive(int n):
    if n < 2:
        return n
    return fib_recursive(n - 1) + fib_recursive(n - 2)


cpdef long workload_sieve(int n):
    cdef bytearray sieve = bytearray(b"\x01") * (n + 1)
    sieve[0] = 0
    sieve[1] = 0
    cdef int i = 2
    cdef int j
    while i * i <= n:
        if sieve[i]:
            j = i * i
            while j <= n:
                sieve[j] = 0
                j += i
        i += 1
    cdef long total = 0
    for i in range(n + 1):
        total += sieve[i]
    return total


cpdef long workload_mandelbrot(int w, int h, int maxit):
    cdef double x_min = -2.0, x_max = 1.0
    cdef double y_min = -1.0, y_max = 1.0
    cdef long total = 0
    cdef int px, py, it
    cdef double x0, y0, x, y, xt
    for py in range(h):
        y0 = y_min + (y_max - y_min) * py / h
        for px in range(w):
            x0 = x_min + (x_max - x_min) * px / w
            x = 0.0
            y = 0.0
            it = 0
            while x * x + y * y < 4.0 and it < maxit:
                xt = x * x - y * y + x0
                y = 2.0 * x * y + y0
                x = xt
                it += 1
            total += it
    return total


cpdef double workload_nbody(int n_steps):
    cdef double PI = 3.141592653589793
    cdef double SOLAR_MASS = 4 * PI * PI
    cdef double DAYS = 365.24
    # Fixed-size 5-body system, flat C arrays
    cdef double[5] x = [0.0,
        4.84143144246472090e+00,
        8.34336671824457987e+00,
        1.28943695621391310e+01,
        1.53796971148509165e+01]
    cdef double[5] y = [0.0,
        -1.16032004402742839e+00,
        4.12479856412430479e+00,
        -1.51111514016986312e+01,
        -2.59193146099879641e+01]
    cdef double[5] z = [0.0,
        -1.03622044471123109e-01,
        -4.03523417114321381e-01,
        -2.23307578892655734e-01,
        1.79258772950371181e-01]
    cdef double[5] vx = [0.0,
        1.66007664274403694e-03 * DAYS,
        -2.76742510726862411e-03 * DAYS,
        2.96460137564761618e-03 * DAYS,
        2.68067772490389322e-03 * DAYS]
    cdef double[5] vy = [0.0,
        7.69901118419740425e-03 * DAYS,
        4.99852801234917238e-03 * DAYS,
        2.37847173959480950e-03 * DAYS,
        1.62824170038242295e-03 * DAYS]
    cdef double[5] vz = [0.0,
        -6.90460016972063023e-05 * DAYS,
        2.30417297573763929e-05 * DAYS,
        -2.96589568540237556e-05 * DAYS,
        -9.51592254519715870e-05 * DAYS]
    cdef double[5] m = [SOLAR_MASS,
        9.54791938424326609e-04 * SOLAR_MASS,
        2.85885980666130812e-04 * SOLAR_MASS,
        4.36624404335156298e-05 * SOLAR_MASS,
        5.15138902046611451e-05 * SOLAR_MASS]
    cdef double dt = 0.01
    cdef int i, j, step
    cdef double dx, dy, dz, d2, d, mag
    for step in range(n_steps):
        for i in range(5):
            for j in range(i + 1, 5):
                dx = x[i] - x[j]
                dy = y[i] - y[j]
                dz = z[i] - z[j]
                d2 = dx * dx + dy * dy + dz * dz
                d = d2 * sqrt(d2)
                mag = dt / d
                vx[i] -= dx * m[j] * mag
                vy[i] -= dy * m[j] * mag
                vz[i] -= dz * m[j] * mag
                vx[j] += dx * m[i] * mag
                vy[j] += dy * m[i] * mag
                vz[j] += dz * m[i] * mag
        for i in range(5):
            x[i] += dt * vx[i]
            y[i] += dt * vy[i]
            z[i] += dt * vz[i]
    return x[0]


cpdef uint32_t workload_crc32(int nbytes):
    cdef uint32_t POLY = 0xEDB88320
    cdef uint32_t crc = 0xFFFFFFFF
    cdef bytes data = bytes(range(256)) * (nbytes // 256)
    cdef int i, k
    cdef int n = len(data)
    cdef unsigned char b
    for i in range(n):
        b = data[i]
        crc ^= b
        for k in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ POLY
            else:
                crc = crc >> 1
    return crc ^ 0xFFFFFFFF


cpdef long workload_dict_heavy(int n_ops):
    cdef dict d = {}
    cdef long state = 1
    cdef long key
    cdef int i
    for i in range(n_ops):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        key = state & 0xFFFF
        d[key] = d.get(key, 0) + i
    cdef long total = 0
    for v in d.values():
        total += <long>v
    return total


cpdef long workload_mpu6502_proxy(int n_insns):
    cdef bytearray rom = bytearray(0x10000)
    cdef int i
    for i in range(0, 0x10000 - 4, 4):
        rom[i] = 0xA9
        rom[i + 1] = i & 0xFF
        rom[i + 2] = 0x8D
        rom[i + 3] = (i + 1) & 0xFF
    cdef int a = 0
    cdef int pc = 0
    cdef long cycles = 0
    cdef int n = 0
    cdef int op, addr
    while n < n_insns:
        op = rom[pc]
        if op == 0xA9:
            a = rom[(pc + 1) & 0xFFFF]
            pc = (pc + 2) & 0xFFFF
            cycles += 2
        elif op == 0x8D:
            addr = rom[(pc + 1) & 0xFFFF] | (rom[(pc + 2) & 0xFFFF] << 8)
            rom[addr] = a
            pc = (pc + 3) & 0xFFFF
            cycles += 4
        else:
            pc = (pc + 1) & 0xFFFF
            cycles += 2
        n += 1
    return cycles


cdef class _Cell:
    cdef public long a, b, c
    def __cinit__(self, long a, long b, long c):
        self.a = a
        self.b = b
        self.c = c
    cpdef long total(self):
        return self.a + self.b + self.c


cpdef long workload_object_churn(int n):
    cdef list cells = []
    cdef int i
    for i in range(n):
        cells.append(_Cell(i, i * 2, i * 3))
    cdef long s = 0
    for c in cells:
        s += (<_Cell>c).total()
    return s
