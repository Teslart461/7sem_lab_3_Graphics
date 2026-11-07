import math
import tkinter as tk
from tkinter import ttk

SIZE = 400            # размер изображения, пикселей
SEGMENTS = 64         # число сегментов вращения вокруг оси Y
PROFILE_POINTS = 28   # число точек образующей кривой
RADIUS = 1.3          # фигура вписывается в шар такого радиуса

# ---- параметры простейшей модели освещённости ----
IA_KA = 0.12          # фоновое освещение Ia*Ka
KD = 0.7              # коэффициент диффузного отражения
KS = 0.6              # коэффициент зеркального отражения
N_PHONG = 40          # показатель степени в модели Фонга
IL = 1.0              # интенсивность источника света
K_CONST = 1.0         # постоянная k в знаменателе затухания
D_SCALE = 0.15        # масштаб расстояния d
LIGHT = (4.0, 5.0, 6.0)   # положение источника света

# ---- камера: две заданные точки ----
CAM_A = (0.0, 1.5, 5.0)
CAM_B = (5.0, 2.5, -1.0)
FRAMES = 60           # число кадров анимации

GRAY = ["#%02x%02x%02x" % (g, g, g) for g in range(256)]   # палитра градаций серого
BG = GRAY[24]


# ============================ векторы ============================
def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def length(a):
    return math.sqrt(dot(a, a))


def normalize(a):
    l = length(a)
    return (a[0] / l, a[1] / l, a[2] / l) if l > 1e-12 else (0.0, 0.0, 0.0)


# ================= Фигура вращения (образующая) =================
def profile(name):
    """Образующая кривая: список точек (r, h) - радиус (расстояние от оси вращения) и высота (координата вдоль оси вращения)."""
    pts = []
    n = PROFILE_POINTS
    for i in range(n):
        t = i / (n - 1)
        if name == "Шар":
            pts.append((math.sin(math.pi * t), -math.cos(math.pi * t)))
        else:  # Ваза: произвольная кривая r(t)
            r = 0.5 + 0.3 * math.sin(2 * math.pi * t) + 0.2 * t
            pts.append((r, -1 + 2 * t))
    if name != "Шар":
        pts.insert(0, (0.0, -1.0))   # точка на оси - закрываем дно вазы
    m = max(math.hypot(r, h) for r, h in pts)   # находим максимально удалённую от центра точку
    return [(r * RADIUS / m, h * RADIUS / m) for r, h in pts]


class Mesh:
    """Сетка из треугольников + нормали в вершинах и нормали граней."""

    def __init__(self, prof):
        n, M = len(prof), SEGMENTS
        # вершины: каждая точка образующей вращается вокруг оси Y
        self.V = []
        for r, h in prof:
            for j in range(M):
                a = 2 * math.pi * j / M
                self.V.append((r * math.cos(a), h, r * math.sin(a)))

        # ---- Триангуляция: каждый четырёхугольник -> 2 треугольника ----
        self.T = []
        for i in range(n - 1):
            for j in range(M):
                j2 = (j + 1) % M
                a, b = i * M + j, (i + 1) * M + j
                c, d = i * M + j2, (i + 1) * M + j2
                self.T.append((a, b, c))
                self.T.append((b, d, c))

        # нормали граней, центры граней; нормаль вершины = сумма нормалей граней
        self.TN, self.TC = [], []
        acc = [[0.0, 0.0, 0.0] for _ in self.V] 
        for a, b, c in self.T:
            va, vb, vc = self.V[a], self.V[b], self.V[c]    # получаем координаты трёх вершин треугольника
            f = cross(sub(vb, va), sub(vc, va))             # перпендикуляр к грани. Его длина ~ площади грани
            self.TN.append(normalize(f))                    # сохраняем нормализованную нормаль грани
            self.TC.append(((va[0] + vb[0] + vc[0]) / 3,
                            (va[1] + vb[1] + vc[1]) / 3,
                            (va[2] + vb[2] + vc[2]) / 3))   # сохраняем центр грани
            for k in (a, b, c):
                for d in range(3):
                    acc[k][d] += f[d]
        # полюса (r = 0): все вершины кольца совпадают - даём им общую нормаль
        for i, (r, h) in enumerate(prof):
            if r < 1e-6:
                s = [sum(acc[i * M + j][d] for j in range(M)) for d in range(3)]
                for j in range(M):
                    acc[i * M + j] = s[:]
        self.N = [normalize(v) for v in acc]




# ================= Камера: плавное движение A -> B =================
def camera_position(t):
    """Камера движется по дуге от A к B (интерполируем направление и расстояние),
    всегда смотрит в центр фигуры."""
    ua, ub = normalize(CAM_A), normalize(CAM_B)
    mix = tuple((1 - t) * ua[i] + t * ub[i] for i in range(3))
    d = normalize(mix)
    dist = (1 - t) * length(CAM_A) + t * length(CAM_B)
    return (d[0] * dist, d[1] * dist, d[2] * dist)




# ===================== Освещение и Закраска =====================
def render(mesh, cam, W, gouraud, specular):
    """Возвращает кадр W x W (список строк, элементы - цвета).
    gouraud=False - плоская закраска (цвет считается один раз на треугольник);
    gouraud=True  - Гуро: интенсивность считается в вершинах и
                    линейно интерполируется по грани."""
    H = W
    cx, cy, cz = cam
    f = normalize((-cx, -cy, -cz))                 # вектор взгляда из камеры в центр
    r = normalize(cross(f, (0.0, 1.0, 0.0)))       # "вправо"
    u = cross(r, f)                                # "вверх"
    # Получаем систему координат камеры: f - вперёд, r - вправо, u - вверх
    focal = 1.4 * W                                # фокусное расстояние
    d0 = length(cam) - RADIUS                      # расстояние до ближайшей точки
    Lx, Ly, Lz = LIGHT


    def intensity(nx, ny, nz, px, py, pz):
        """I = Ia*Ka + Il/(k+d) * (Kd*(N.L) + Ks*(R.S)^n)"""

        sx, sy, sz = cx - px, cy - py, cz - pz          # S — единичный вектор из точки на камеру
        dist = math.sqrt(sx * sx + sy * sy + sz * sz)
        sx, sy, sz = sx / dist, sy / dist, sz / dist 

        if nx * sx + ny * sy + nz * sz < 0:             # освещаем ту сторону, что видна
            nx, ny, nz = -nx, -ny, -nz  

        lx, ly, lz = Lx - px, Ly - py, Lz - pz          # L — единичный вектор из точки на источник света
        ll = math.sqrt(lx * lx + ly * ly + lz * lz)
        lx, ly, lz = lx / ll, ly / ll, lz / ll

        nl = nx * lx + ny * ly + nz * lz                # N * L — косинус угла между нормалью и светом
        if nl <= 0:                                     # свет падает с обратной стороны, остаётся только фон
            return IA_KA
        
        val = KD * nl                                   # диффузная часть (Ламберт)

        if specular:
            rx, ry, rz = 2 * nl * nx - lx, 2 * nl * ny - ly, 2 * nl * nz - lz  # R — отраженный вектор
            rs = rx * sx + ry * sy + rz * sz       # R * S — косинус угла между отражённым вектором и направлением на камеру
            if rs > 0:
                val += KS * rs ** N_PHONG          # зеркальная часть (Фонг)

        d = max(0.0, dist - d0) * D_SCALE          # d — глубина точки относительно ближней границы объекта, умноженная на масштаб
        return min(1.0, IA_KA + IL / (K_CONST + d) * val)


    # проекция вершин + 1/z (для z-буфера и перспективно-верной интерполяции)
    pts, ws = [], []
    for (px, py, pz) in mesh.V:
        dx, dy, dz = px - cx, py - cy, pz - cz      # вектор от камеры (координаты точки в системе коорд-ат камеры)
        zc = dx * f[0] + dy * f[1] + dz * f[2]      # глубина 
        w = 1.0 / zc                                # деление на zc даёт перспективу (дальше значит меньше)
        pts.append((W / 2 + focal * (dx * r[0] + dy * r[1] + dz * r[2]) * w,
                    H / 2 - focal * (dx * u[0] + dy * u[1] + dz * u[2]) * w))   # экранные координаты
        ws.append(w)                                                            # чем больше 1/z, тем ближе точка

    if gouraud:
        # шаг 3 метода Гуро: интенсивность в вершинах (по усреднённым нормалям)
        vint = [intensity(n[0], n[1], n[2], p[0], p[1], p[2])
                for p, n in zip(mesh.V, mesh.N)]
    else:
        # плоская закраска: одна интенсивность на грань (в её центре)
        tint = [intensity(n[0], n[1], n[2], c[0], c[1], c[2])
                for n, c in zip(mesh.TN, mesh.TC)]

    rows = [[BG] * W for _ in range(H)]
    zbuf = [[0.0] * W for _ in range(H)]           # хранит 1/z, больше = ближе

    for ti, (a, b, c) in enumerate(mesh.T):        # цикл по треугольникам. Берём экранные точки, 1/z и яркости трёх вершин.
        p = (pts[a], pts[b], pts[c])               # экранные координаты трех вершин треугольника
        w3 = (ws[a], ws[b], ws[c])                 # значения глубины (1/z) для этих трех вершин
        if gouraud:
            i3 = (vint[a], vint[b], vint[c])
        else:                                      # в плоском режиме все три яркости одинаковы
            v = tint[ti]
            i3 = (v, v, v)

        # диапазон строк y, которые пересекает треугольник
        ys = max(0, math.ceil(min(q[1] for q in p) - 0.5))      # самая верхняя точка треугольника на экране по координате y
        ye = min(H, math.ceil(max(q[1] for q in p) - 0.5))      # самая нижняя точка треугольника на экране по координате y

        for y in range(ys, ye):                    # сканирующие строки
            yc = y + 0.5                           # координата центра текущей строки пикселей
            hit = []
            for i, j in ((0, 1), (1, 2), (2, 0)):  # обходим все три ребра треугольника
                ya, yb = p[i][1], p[j][1]
                if (ya <= yc < yb) or (yb <= yc < ya):          # пересекает ли наша горизонтальная линия yc текущее ребро
                    t = (yc - ya) / (yb - ya)                   # насколько глубоко линия yc врезалась в ребро между ya и yb (от 0 до 1)
                    hit.append((p[i][0] + t * (p[j][0] - p[i][0]),      # координата x пересечения линии yc с ребром
                                w3[i] + t * (w3[j] - w3[i]),            # значение глубины 1/z в точке пересечения
                                i3[i] + t * (i3[j] - i3[i])))           # значение яркости в точке пересечения 
            if len(hit) < 2:
                continue

            hit.sort()
            xl, wl, il = hit[0]                    # левый конец отрезка QR
            xr, wr, ir = hit[-1]                   # правый конец
            if xr - xl < 1e-9:
                continue
            
            xs = max(0, math.ceil(xl - 0.5))       # левая граница отрезка QR (включительно)
            xe = min(W, math.ceil(xr - 0.5))       # правая граница отрезка QR (не включительно)
            if xe <= xs:
                continue

            # линейная интерполяция вдоль строки, инкрементально
            inv = 1.0 / (xr - xl)           # коэффициент для вычисления шага изменения
            dw = (wr - wl) * inv            # шаг изменения глубины на один пиксель
            di = (ir - il) * inv            # шаг изменения яркости на один пиксель

            # первый пиксель xs находится не точно на границе xl
            s = xs + 0.5 - xl           
            w = wl + dw * s               
            val = il + di * s

            zrow, row = zbuf[y], rows[y]
            for x in range(xs, xe):                                             # идем пиксель за пикселем слева направо
                if w > zrow[x]:                                                 # Z-буфер: если текущая точка БЛИЖЕ, чем то, что нарисовано тут раньше
                    zrow[x] = w                                                 
                    row[x] = GRAY[int(min(1.0, max(0.0, val)) * 255 + 0.5)]     # красим пиксель в нужный оттенок серого
                w += dw                                                         # шагаем по глубине для следующего пикселя
                val += di                                                       # шагаем по яркости для следующего пикселя
    return rows



# ============================== GUI ==============================
class App:
    def __init__(self, root):
        self.root = root
        root.title("Лабораторная работа 3 - закраска Гуро")
        self.anim = False
        self.img = None
        self.meshes = {}
        self.pending = False
        self.final_job = None

        top = ttk.Frame(root, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="Фигура:").pack(side="left")
        self.fig = tk.StringVar(value="Шар")
        cb = ttk.Combobox(top, textvariable=self.fig, values=["Шар", "Ваза"],
                          state="readonly", width=7)
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.draw(1))

        self.mode = tk.StringVar(value="gouraud")
        ttk.Radiobutton(top, text="Плоская", variable=self.mode, value="flat",
                        command=lambda: self.draw(1)).pack(side="left", padx=(8, 0))
        ttk.Radiobutton(top, text="Гуро", variable=self.mode, value="gouraud",
                        command=lambda: self.draw(1)).pack(side="left")

        self.spec = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Блики", variable=self.spec,
                        command=lambda: self.draw(1)).pack(side="left", padx=8)

        self.btn = ttk.Button(top, text="Анимация A -> B", command=self.toggle)
        self.btn.pack(side="left", padx=4)
        self.status = ttk.Label(top, text="")
        self.status.pack(side="left", padx=6)

        self.canvas = tk.Canvas(root, width=SIZE, height=SIZE, bg=BG,
                                highlightthickness=0)
        self.canvas.pack(padx=6, pady=(0, 6))

        self.t = tk.DoubleVar(value=0.0)
        self.scale = tk.Scale(root, variable=self.t, from_=0, to=1, resolution=0.001,
                              orient="horizontal", showvalue=True, length=SIZE,
                              label="Положение камеры (A -> B), стрелки <- / ->",
                              command=lambda v: self.schedule())
        self.scale.pack(fill="x", padx=6, pady=(0, 6))

        root.bind("<Left>", lambda e: self.nudge(-0.02))
        root.bind("<Right>", lambda e: self.nudge(0.02))
        root.after(100, lambda: self.draw(1))


    def nudge(self, dt):
        if not self.anim:
            self.t.set(min(1.0, max(0.0, self.t.get() + dt)))
            self.schedule()

    def schedule(self):
        """Перерисовка при движении ползунка: быстро (в половинном разрешении),
        а через паузу - начисто."""
        if self.anim:
            return
        if not self.pending:
            self.pending = True
            self.root.after(1, self._quick)

    def _quick(self):
        self.pending = False
        self.draw(2)
        if self.final_job:
            self.root.after_cancel(self.final_job)
        self.final_job = self.root.after(250, lambda: self.draw(1))

    def draw(self, scale):
        name = self.fig.get()
        if name not in self.meshes:
            self.meshes[name] = Mesh(profile(name))
        mesh = self.meshes[name]
        W = SIZE // scale
        rows = render(mesh, camera_position(self.t.get()), W,
                      self.mode.get() == "gouraud", self.spec.get())
        img = tk.PhotoImage(width=W, height=W)
        img.put(" ".join("{" + " ".join(row) + "}" for row in rows))
        self.img = img.zoom(scale) if scale > 1 else img
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.img)
        self.status.config(text="Треугольников: %d" % len(mesh.T))
        self.root.update_idletasks()

    def toggle(self):
        if self.anim:
            self.anim = False
            self.btn.config(text="Анимация A -> B")
            self.draw(1)
            return
        self.anim = True
        self.btn.config(text="Стоп")
        if self.t.get() >= 1.0 - 1e-9:
            self.t.set(0.0)
        self.step()

    def step(self):
        if not self.anim:
            return
        t = self.t.get()
        self.draw(2)
        if t >= 1.0 - 1e-9:
            self.anim = False
            self.btn.config(text="Анимация A -> B")
            self.draw(1)
            return
        self.t.set(min(1.0, t + 1.0 / FRAMES))
        self.root.after(1, self.step)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()