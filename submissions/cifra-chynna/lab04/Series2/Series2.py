import json
import math
import re
from pathlib import Path


L = 20.0
ANGLES_DEG = [1, 2, 5, 10, 15, 20, 30]
TOLERANCE_PCT = 0.1


def geometric_sum(x, terms):
  return sum(x ** k for k in range(terms + 1))


def power_series(x, coefficients):
  return sum(coefficient * x ** k for k, coefficient in enumerate(coefficients))


def sin_maclaurin(theta, terms):
  return sum(
    (-1) ** n * theta ** (2 * n + 1) / math.factorial(2 * n + 1)
    for n in range(terms)
  )


def sin_taylor(theta, center, terms):
  sin_center = math.sin(center)
  cos_center = math.cos(center)
  derivatives = [sin_center, cos_center, -sin_center, -cos_center]
  return sum(
    derivatives[n % 4] * (theta - center) ** n / math.factorial(n)
    for n in range(terms)
  )


def percent_error(approximation, exact):
  return abs(approximation - exact) / abs(exact) * 100 if exact else 0.0


def build_dashboard_data():
  center = math.radians(10)
  data = {"geo": [], "mac3": [], "part4": {}, "part5": {}, "part6_min": []}

  for x in [0.5, 0.8, 0.9]:
    exact = 1 / (1 - x)
    terms = []
    for number in [2, 5, 10, 20, 50]:
      approximation = geometric_sum(x, number)
      terms.append({"N": number, "approx": approximation, "pct": percent_error(approximation, exact)})
    data["geo"].append({"x": x, "exact": exact, "terms": terms})

  exact_10 = math.sin(center)
  for number in [1, 2, 3, 4]:
    approximation = sin_maclaurin(center, number)
    data["mac3"].append({"N": number, "approx": approximation, "pct": percent_error(approximation, exact_10)})

  for number in [1, 2, 3, 4]:
    rows = []
    for degrees in ANGLES_DEG:
      radians = math.radians(degrees)
      exact = L * math.sin(radians)
      approximation = L * sin_maclaurin(radians, number)
      rows.append({"deg": degrees, "exact": exact, "approx": approximation,
             "abs_err": abs(approximation - exact), "pct": percent_error(approximation, exact)})
    data["part4"][str(number)] = rows

  for number in [1, 2, 3, 4]:
    rows = []
    for degrees in ANGLES_DEG:
      radians = math.radians(degrees)
      exact = math.sin(radians)
      mac = sin_maclaurin(radians, number)
      tay = sin_taylor(radians, center, number)
      rows.append({"deg": degrees, "exact": exact, "mac": mac, "mac_pct": percent_error(mac, exact),
             "tay": tay, "tay_pct": percent_error(tay, exact)})
    data["part5"][str(number)] = rows

  for degrees in ANGLES_DEG:
    radians = math.radians(degrees)
    exact = math.sin(radians)
    minimum = {}
    for name, approximation in [("mac", sin_maclaurin),
                   ("tay", lambda value, n: sin_taylor(value, center, n))]:
      for number in range(1, 20):
        error = percent_error(approximation(radians, number), exact)
        if error < TOLERANCE_PCT:
          minimum[f"{name}_n"] = number
          minimum[f"{name}_pct"] = error
          break
    data["part6_min"].append({"deg": degrees, **minimum})

  fine_degrees = [index * 0.5 for index in range(1, 65)]
  fine_radians = [math.radians(degrees) for degrees in fine_degrees]
  fine_exact = [math.sin(value) for value in fine_radians]
  data.update({"fine_degs": fine_degrees, "fine_exact": fine_exact,
         "fine_mac": {}, "fine_tay": {}, "fine_mac_pct": {}, "fine_tay_pct": {}})
  for number in [1, 2, 3, 4]:
    mac_values = [sin_maclaurin(value, number) for value in fine_radians]
    tay_values = [sin_taylor(value, center, number) for value in fine_radians]
    data["fine_mac"][str(number)] = mac_values
    data["fine_tay"][str(number)] = tay_values
    data["fine_mac_pct"][str(number)] = [percent_error(value, exact) for value, exact in zip(mac_values, fine_exact)]
    data["fine_tay_pct"][str(number)] = [percent_error(value, exact) for value, exact in zip(tay_values, fine_exact)]

  for name, approximation in [("mac", sin_maclaurin),
                 ("tay", lambda value, n: sin_taylor(value, center, n))]:
    data[f"conv_{name}"] = {}
    for degrees in [5, 10, 20, 30]:
      radians = math.radians(degrees)
      exact = math.sin(radians)
      data[f"conv_{name}"][str(degrees)] = [
        percent_error(approximation(radians, number), exact) for number in range(1, 8)
      ]

  data["small_angle"] = []
  for degrees in range(1, 35):
    radians = math.radians(degrees)
    data["small_angle"].append({"deg": degrees, "pct": percent_error(radians, math.sin(radians))})
  return data


HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>How Accurate Is Good Enough? — Civil Engineering Series Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root {
  --navy:    #0a1628;
  --navy2:   #0f1f3d;
  --navy3:   #1a2f50;
  --steel:   #2563a8;
  --steel2:  #3b82c4;
  --sky:     #93c5fd;
  --amber:   #f59e0b;
  --amber2:  #fcd34d;
  --white:   #f0f6ff;
  --muted:   #64748b;
  --muted2:  #94a3b8;
  --success: #34d399;
  --danger:  #f87171;
  --grid:    rgba(147,197,253,0.08);
  --border:  rgba(147,197,253,0.15);
  --mono:    'IBM Plex Mono', monospace;
  --sans:    'Inter', sans-serif;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html { scroll-behavior: smooth; }

body {
  font-family: var(--sans);
  background: var(--navy);
  color: var(--white);
  display: flex;
  min-height: 100vh;
  overflow-x: hidden;
}

/* ── Blueprint grid background ── */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px);
  background-size: 40px 40px;
  pointer-events: none;
  z-index: 0;
}

/* ── Sidebar ── */
#sidebar {
  position: fixed;
  left: 0; top: 0; bottom: 0;
  width: 230px;
  background: var(--navy2);
  border-right: 1px solid var(--border);
  z-index: 100;
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow-y: auto;
}

.sidebar-header {
  padding: 28px 20px 20px;
  border-bottom: 1px solid var(--border);
}

.sidebar-header .logo {
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--amber);
  margin-bottom: 10px;
  text-transform: uppercase;
}

.sidebar-header h1 {
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--white);
  line-height: 1.5;
}

.sidebar-header p {
  font-size: 11px;
  color: var(--muted2);
  margin-top: 6px;
  line-height: 1.5;
}

nav { flex: 1; padding: 16px 0; }

nav a {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 20px;
  text-decoration: none;
  font-size: 12px;
  color: var(--muted2);
  border-left: 2px solid transparent;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
  cursor: pointer;
}

nav a:hover { color: var(--white); background: rgba(147,197,253,0.05); }

nav a.active {
  color: var(--amber);
  border-left-color: var(--amber);
  background: rgba(245,158,11,0.07);
}

nav a .nav-num {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--steel2);
  width: 20px;
  flex-shrink: 0;
}

nav a.active .nav-num { color: var(--amber2); }

.sidebar-footer {
  padding: 16px 20px;
  border-top: 1px solid var(--border);
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  line-height: 1.6;
}

/* ── Main content ── */
#main {
  margin-left: 230px;
  flex: 1;
  position: relative;
  z-index: 1;
}

/* ── Hero ── */
#hero {
  background: linear-gradient(135deg, var(--navy2) 0%, var(--navy3) 100%);
  border-bottom: 1px solid var(--border);
  padding: 56px 60px 48px;
  position: relative;
  overflow: hidden;
}

#hero::after {
  content: 'sin(θ)';
  position: absolute;
  right: 60px;
  top: 50%;
  transform: translateY(-50%);
  font-family: var(--mono);
  font-size: 120px;
  font-weight: 600;
  color: rgba(147,197,253,0.06);
  pointer-events: none;
  user-select: none;
}

#hero .tag {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--amber);
  letter-spacing: 0.1em;
  margin-bottom: 16px;
}

#hero h2 {
  font-size: 36px;
  font-weight: 300;
  line-height: 1.2;
  max-width: 600px;
  letter-spacing: -0.02em;
}

#hero h2 strong { font-weight: 600; }

#hero p {
  margin-top: 16px;
  font-size: 14px;
  color: var(--muted2);
  max-width: 520px;
  line-height: 1.7;
}

.hero-stats {
  display: flex;
  gap: 40px;
  margin-top: 36px;
}

.hero-stat .val {
  font-family: var(--mono);
  font-size: 28px;
  font-weight: 600;
  color: var(--amber);
}

.hero-stat .lbl {
  font-size: 12px;
  color: var(--muted2);
  margin-top: 2px;
}

/* ── Sections ── */
.section {
  display: none;
  padding: 48px 60px;
  min-height: calc(100vh - 200px);
}

.section.visible { display: block; }

.section-title {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--steel2);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-bottom: 8px;
}

.section h2 {
  font-size: 26px;
  font-weight: 500;
  margin-bottom: 6px;
  letter-spacing: -0.01em;
}

.section .section-desc {
  font-size: 13px;
  color: var(--muted2);
  max-width: 660px;
  line-height: 1.7;
  margin-bottom: 36px;
}

/* ── Formula box ── */
.formula-box {
  background: var(--navy3);
  border: 1px solid var(--border);
  border-left: 3px solid var(--amber);
  border-radius: 6px;
  padding: 18px 24px;
  margin-bottom: 32px;
  font-family: var(--mono);
  font-size: 13px;
  line-height: 1.9;
  color: var(--sky);
}

.formula-box .comment { color: var(--muted); font-size: 11px; }

/* ── Data tables ── */
.table-wrap { overflow-x: auto; margin-bottom: 32px; }

table {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--mono);
  font-size: 12px;
}

thead th {
  background: var(--navy3);
  padding: 10px 14px;
  text-align: left;
  font-weight: 500;
  color: var(--sky);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

tbody tr { border-bottom: 1px solid rgba(147,197,253,0.06); }
tbody tr:hover { background: rgba(147,197,253,0.04); }

tbody td {
  padding: 9px 14px;
  color: var(--muted2);
  white-space: nowrap;
}

td.num { text-align: right; color: var(--white); }

td.good  { color: var(--success); font-weight: 500; }
td.ok    { color: var(--amber2); }
td.bad   { color: var(--danger); }

/* ── Tabs ── */
.tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 28px;
  flex-wrap: wrap;
}

.tab-btn {
  font-family: var(--mono);
  font-size: 11px;
  padding: 7px 14px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted2);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}

.tab-btn:hover { color: var(--white); border-color: var(--steel2); }
.tab-btn.active { background: var(--amber); color: var(--navy); border-color: var(--amber); font-weight: 600; }

.tab-panel { display: none; }
.tab-panel.active { display: block; }

/* ── Chart cards ── */
.chart-card {
  background: var(--navy2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 28px;
  margin-bottom: 28px;
}

.chart-card h3 {
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 4px;
}

.chart-card p {
  font-size: 12px;
  color: var(--muted2);
  margin-bottom: 20px;
  line-height: 1.6;
}

.chart-wrap { position: relative; }

/* ── Grid layout ── */
.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

/* ── Callout ── */
.callout {
  background: rgba(245,158,11,0.08);
  border: 1px solid rgba(245,158,11,0.25);
  border-radius: 6px;
  padding: 18px 24px;
  margin-bottom: 28px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--amber2);
}

.callout strong { color: var(--amber); }

/* ── Recommendation ── */
.rec-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px,1fr));
  gap: 16px;
  margin-bottom: 32px;
}

.rec-card {
  background: var(--navy3);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
}

.rec-card .scenario {
  font-family: var(--mono);
  font-size: 18px;
  font-weight: 600;
  color: var(--amber);
  margin-bottom: 8px;
}

.rec-card .method {
  font-size: 13px;
  font-weight: 500;
  color: var(--white);
  margin-bottom: 4px;
}

.rec-card .detail {
  font-size: 12px;
  color: var(--muted2);
  line-height: 1.5;
}

.verdict-box {
  background: linear-gradient(135deg, rgba(52,211,153,0.1), rgba(37,99,168,0.1));
  border: 1px solid rgba(52,211,153,0.3);
  border-radius: 8px;
  padding: 28px 32px;
  margin-bottom: 28px;
}

.verdict-box h3 {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--success);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-bottom: 12px;
}

.verdict-box p {
  font-size: 14px;
  line-height: 1.8;
  color: var(--white);
  max-width: 680px;
}

.verdict-box ul {
  margin-top: 14px;
  padding-left: 20px;
  font-size: 13px;
  color: var(--muted2);
  line-height: 2;
}

.verdict-box ul li strong { color: var(--sky); }

/* ── Progress indicator ── */
.pct-bar-wrap { display: flex; align-items: center; gap: 10px; }
.pct-bar {
  flex: 1;
  height: 4px;
  background: var(--navy3);
  border-radius: 2px;
  overflow: hidden;
  max-width: 100px;
}
.pct-bar-fill { height: 100%; background: var(--amber); border-radius: 2px; transition: width 0.3s; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--navy); }
::-webkit-scrollbar-thumb { background: var(--navy3); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--steel); }

@media (max-width: 900px) {
  #sidebar { width: 56px; }
  #sidebar .sidebar-header h1,
  #sidebar .sidebar-header p,
  #sidebar .sidebar-footer,
  nav a span:not(.nav-num) { display: none; }
  nav a { justify-content: center; padding: 12px; }
  #main { margin-left: 56px; }
  #hero, .section { padding: 32px 28px; }
  .grid-2 { grid-template-columns: 1fr; }
  #hero::after { display: none; }
}
</style>
</head>
<body>

<!-- ── SIDEBAR ── -->
<aside id="sidebar">
  <div class="sidebar-header">
    <div class="logo">CE · Series Lab</div>
    <h1>How Accurate Is Good Enough?</h1>
    <p>y = L sin(θ), L = 20 m</p>
  </div>
  <nav>
    <a href="#" onclick="showSection('s1')" id="nav-s1" class="active">
      <span class="nav-num">P1</span><span>Geometric Series</span>
    </a>
    <a href="#" onclick="showSection('s2')" id="nav-s2">
      <span class="nav-num">P2</span><span>Power Series</span>
    </a>
    <a href="#" onclick="showSection('s3')" id="nav-s3">
      <span class="nav-num">P3</span><span>Maclaurin Series</span>
    </a>
    <a href="#" onclick="showSection('s4')" id="nav-s4">
      <span class="nav-num">P4</span><span>Engineering Tables</span>
    </a>
    <a href="#" onclick="showSection('s5')" id="nav-s5">
      <span class="nav-num">P5</span><span>Taylor Series</span>
    </a>
    <a href="#" onclick="showSection('s6')" id="nav-s6">
      <span class="nav-num">P6</span><span>Error Tolerance</span>
    </a>
    <a href="#" onclick="showSection('s7')" id="nav-s7">
      <span class="nav-num">P7</span><span>Recommendation</span>
    </a>
  </nav>
  <div class="sidebar-footer">
    CE Students · Sept 2026<br>
    L = 20 m · tol = 0.1%
  </div>
</aside>

<!-- ── MAIN ── -->
<main id="main">

  <!-- Hero -->
  <div id="hero">
    <div class="tag">Integrated Python Exercise — Civil Engineering</div>
    <h2>How Accurate Is<br><strong>Good Enough?</strong></h2>
    <p>Approximating y = L·sin(θ) using infinite series — from geometric sums to Taylor expansions — with full error analysis and engineering decision-making.</p>
    <div class="hero-stats">
      <div class="hero-stat">
        <div class="val">7</div>
        <div class="lbl">Parts covered</div>
      </div>
      <div class="hero-stat">
        <div class="val">0.1%</div>
        <div class="lbl">Error tolerance</div>
      </div>
      <div class="hero-stat">
        <div class="val">~5°</div>
        <div class="lbl">Small-angle limit</div>
      </div>
      <div class="hero-stat">
        <div class="val">N=2</div>
        <div class="lbl">Min terms for θ &lt; 30°</div>
      </div>
    </div>
  </div>

  <!-- ══════════════════════════════════════════════════════════════ -->
  <!-- PART 1 -->
  <!-- ══════════════════════════════════════════════════════════════ -->
  <section id="s1" class="section visible">
    <div class="section-title">Part 1</div>
    <h2>Geometric Series</h2>
    <p class="section-desc">
      The geometric series S<sub>N</sub> = 1 + x + x² + … + x<sup>N</sup> converges to 1/(1−x) for |x| &lt; 1.
      We compute partial sums explicitly using a loop and compare to the exact closed form.
    </p>

    <div class="formula-box">
      <span class="comment"># Python implementation — no closed form used</span><br>
      def geometric_sum(x, N):<br>
      &nbsp;&nbsp;&nbsp;&nbsp;total = 0.0<br>
      &nbsp;&nbsp;&nbsp;&nbsp;for k in range(N + 1):<br>
      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;total += x ** k<br>
      &nbsp;&nbsp;&nbsp;&nbsp;return total<br>
      <br>
      <span class="comment"># Exact:  1 / (1 − x)   for |x| &lt; 1</span>
    </div>

    <div class="tabs">
      <button class="tab-btn active" onclick="switchTab('geo','g05',this)">x = 0.5</button>
      <button class="tab-btn" onclick="switchTab('geo','g08',this)">x = 0.8</button>
      <button class="tab-btn" onclick="switchTab('geo','g09',this)">x = 0.9</button>
    </div>

    <div id="geo-g05" class="tab-panel active"><div class="table-wrap" id="gt05"></div></div>
    <div id="geo-g08" class="tab-panel"><div class="table-wrap" id="gt08"></div></div>
    <div id="geo-g09" class="tab-panel"><div class="table-wrap" id="gt09"></div></div>

    <div class="chart-card">
      <h3>Convergence Speed by x value</h3>
      <p>Percentage error vs. number of terms — note the dramatic difference between x = 0.5 and x = 0.9.</p>
      <div class="chart-wrap" style="height:280px">
        <canvas id="geoChart"></canvas>
      </div>
    </div>

    <div class="callout">
      <strong>Key insight:</strong> Convergence speed depends on x. For x = 0.5 each term is half the previous — 20 terms gives 0.000005% error. For x = 0.9, terms shrink slowly (0.9<sup>N</sup>) — 50 terms still leaves 0.46% error.
    </div>
  </section>

  <!-- ══════════════════════════════════════════════════════════════ -->
  <!-- PART 2 -->
  <!-- ══════════════════════════════════════════════════════════════ -->
  <section id="s2" class="section">
    <div class="section-title">Part 2</div>
    <h2>Power Series</h2>
    <p class="section-desc">
      The geometric series generalises to a power series P<sub>N</sub>(x) = a₀ + a₁x + a₂x² + … where the coefficients aₖ determine the function being approximated. A finite polynomial is a truncated power series; an infinite one can represent sin, cos, exp, and every other transcendental function.
    </p>

    <div class="formula-box">
      def power_series(x, coefficients):<br>
      &nbsp;&nbsp;&nbsp;&nbsp;<span class="comment">"""Evaluate P_N(x) = Σ aₖ · xᵏ  for k = 0 … N"""</span><br>
      &nbsp;&nbsp;&nbsp;&nbsp;result = 0.0<br>
      &nbsp;&nbsp;&nbsp;&nbsp;for k, a_k in enumerate(coefficients):<br>
      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;result += a_k * (x ** k)<br>
      &nbsp;&nbsp;&nbsp;&nbsp;return result
    </div>

    <div class="grid-2">
      <div class="chart-card">
        <h3>Geometric → Power Series progression</h3>
        <p>Every step in the chain is a power series with different coefficients.</p>
        <div style="font-family: var(--mono); font-size: 12px; line-height: 2.2; color: var(--sky); margin-top: 8px;">
          Geometric:&nbsp;&nbsp; a₀=1, a₁=1, a₂=1 … aₙ=1<br>
          sin(θ):&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; a₀=0, a₁=1, a₂=0, a₃=−1/6 …<br>
          cos(θ):&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; a₀=1, a₁=0, a₂=−½, a₃=0 …<br>
          eˣ:&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; a₀=1, a₁=1, a₂=½, a₃=1/6 …
        </div>
      </div>
      <div class="chart-card">
        <h3>Demo: sin(30°) via power_series()</h3>
        <p>Using Maclaurin coefficients [0, 1, 0, −1/6, 0, 1/120, 0, −1/5040]</p>
        <div style="font-family: var(--mono); font-size: 13px; line-height: 2.2; margin-top: 8px;">
          <span style="color:var(--muted2)">x = π/6 = </span><span style="color:var(--white)">0.523599 rad</span><br>
          <span style="color:var(--muted2)">power_series() = </span><span style="color:var(--amber)">0.4999999919</span><br>
          <span style="color:var(--muted2)">math.sin(30°) = </span><span style="color:var(--success)">0.5000000000</span><br>
          <span style="color:var(--muted2)">Abs error &nbsp;&nbsp;&nbsp;= </span><span style="color:var(--sky)">8.1 × 10⁻⁹</span>
        </div>
      </div>
    </div>
  </section>

  <!-- ══════════════════════════════════════════════════════════════ -->
  <!-- PART 3 -->
  <!-- ══════════════════════════════════════════════════════════════ -->
  <section id="s3" class="section">
    <div class="section-title">Part 3</div>
    <h2>Maclaurin Series for sin(θ)</h2>
    <p class="section-desc">
      The Maclaurin series expands sin(θ) around θ = 0. Each additional term adds one more odd-power contribution and reduces the error by roughly θ²/(2n(2n+1)).
    </p>

    <div class="formula-box">
      sin(θ) = θ − θ³/3! + θ⁵/5! − θ⁷/7! + … = Σ (−1)ⁿ · θ<sup>2n+1</sup> / (2n+1)!<br><br>
      def sin_maclaurin(theta, N):<br>
      &nbsp;&nbsp;&nbsp;&nbsp;result = 0.0<br>
      &nbsp;&nbsp;&nbsp;&nbsp;for n in range(N):<br>
      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;sign = (−1) ** n<br>
      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;result += sign * (theta ** (2*n+1)) / factorial(2*n+1)<br>
      &nbsp;&nbsp;&nbsp;&nbsp;return result
    </div>

    <div class="callout" style="margin-bottom: 20px;">
      <strong>Investigation: θ = 10° = 0.174533 rad</strong> &nbsp;·&nbsp; Exact sin(10°) = 0.1736481777
    </div>

    <div class="table-wrap" id="mac3table"></div>

    <div class="chart-card">
      <h3>Error reduction at θ = 10°</h3>
      <p>Each additional Maclaurin term cuts the error by roughly 3 orders of magnitude at this angle.</p>
      <div class="chart-wrap" style="height:260px">
        <canvas id="mac3chart"></canvas>
      </div>
    </div>
  </section>

  <!-- ══════════════════════════════════════════════════════════════ -->
  <!-- PART 4 -->
  <!-- ══════════════════════════════════════════════════════════════ -->
  <section id="s4" class="section">
    <div class="section-title">Part 4</div>
    <h2>Engineering Investigation — y = 20·sin(θ)</h2>
    <p class="section-desc">
      Applying the Maclaurin approximation to the structural geometry problem. L = 20 m, angles 1°–30°, series truncated at N = 1, 2, 3, 4 terms.
    </p>

    <div class="tabs">
      <button class="tab-btn active" onclick="switchTab('p4','p4n1',this)">N = 1 term</button>
      <button class="tab-btn" onclick="switchTab('p4','p4n2',this)">N = 2 terms</button>
      <button class="tab-btn" onclick="switchTab('p4','p4n3',this)">N = 3 terms</button>
      <button class="tab-btn" onclick="switchTab('p4','p4n4',this)">N = 4 terms</button>
    </div>

    <div id="p4-p4n1" class="tab-panel active"><div class="table-wrap" id="p4t1"></div></div>
    <div id="p4-p4n2" class="tab-panel"><div class="table-wrap" id="p4t2"></div></div>
    <div id="p4-p4n3" class="tab-panel"><div class="table-wrap" id="p4t3"></div></div>
    <div id="p4-p4n4" class="tab-panel"><div class="table-wrap" id="p4t4"></div></div>

    <div class="chart-card">
      <h3>y = 20·sin(θ) — Maclaurin approximations vs. exact</h3>
      <p>Select terms to overlay. N=3 is visually indistinguishable from exact across the full range.</p>
      <div class="chart-wrap" style="height:300px">
        <canvas id="engChart"></canvas>
      </div>
    </div>

    <div class="callout">
      <strong>Analysis:</strong> Error grows with angle (higher-order terms matter more as θ increases).
      Adding terms dramatically reduces error at all angles. For θ &lt; 5°, N = 2 is more than sufficient.
      For θ &gt; 20°, N = 3–4 is needed to stay below 0.1%.
    </div>
  </section>

  <!-- ══════════════════════════════════════════════════════════════ -->
  <!-- PART 5 -->
  <!-- ══════════════════════════════════════════════════════════════ -->
  <section id="s5" class="section">
    <div class="section-title">Part 5</div>
    <h2>Taylor Series — centered at a = 10°</h2>
    <p class="section-desc">
      The Taylor series expands around any point a, not just zero. Maclaurin is simply Taylor with a = 0. By centering near the angle of interest, we can reduce the number of terms needed — but only in that neighbourhood.
    </p>

    <div class="formula-box">
      f(θ) = f(a) + f'(a)(θ−a) + f''(a)/2!(θ−a)² + …<br><br>
      <span class="comment"># Derivatives of sin cycle every 4 terms:</span><br>
      <span class="comment"># n%4=0 → +sin(a) &nbsp; n%4=1 → +cos(a) &nbsp; n%4=2 → −sin(a) &nbsp; n%4=3 → −cos(a)</span>
    </div>

    <div class="tabs">
      <button class="tab-btn active" onclick="switchTab('p5','p5n1',this)">N = 1</button>
      <button class="tab-btn" onclick="switchTab('p5','p5n2',this)">N = 2</button>
      <button class="tab-btn" onclick="switchTab('p5','p5n3',this)">N = 3</button>
      <button class="tab-btn" onclick="switchTab('p5','p5n4',this)">N = 4</button>
    </div>

    <div id="p5-p5n1" class="tab-panel active"><div class="table-wrap" id="p5t1"></div></div>
    <div id="p5-p5n2" class="tab-panel"><div class="table-wrap" id="p5t2"></div></div>
    <div id="p5-p5n3" class="tab-panel"><div class="table-wrap" id="p5t3"></div></div>
    <div id="p5-p5n4" class="tab-panel"><div class="table-wrap" id="p5t4"></div></div>

    <div class="grid-2">
      <div class="chart-card">
        <h3>Function comparison — N = 3 terms</h3>
        <p>Exact sin(θ), Maclaurin (a=0°), Taylor (a=10°). Taylor hugs exact near 10°; Maclaurin is better below 5°.</p>
        <div class="chart-wrap" style="height:280px">
          <canvas id="funcChart"></canvas>
        </div>
      </div>
      <div class="chart-card">
        <h3>Percentage error by angle — N = 3</h3>
        <p>Taylor error dips to zero at 10° (the expansion point), then rises. Maclaurin error rises monotonically.</p>
        <div class="chart-wrap" style="height:280px">
          <canvas id="errChart3"></canvas>
        </div>
      </div>
    </div>
  </section>

  <!-- ══════════════════════════════════════════════════════════════ -->
  <!-- PART 6 -->
  <!-- ══════════════════════════════════════════════════════════════ -->
  <section id="s6" class="section">
    <div class="section-title">Part 6</div>
    <h2>Engineering Decision — Error Tolerance</h2>
    <p class="section-desc">
      Requirement: less than 0.1% error. We find the minimum number of terms needed for each angle under both Maclaurin and Taylor series, and identify the critical angle for the small-angle approximation sin(θ) ≈ θ.
    </p>

    <div class="chart-card" style="margin-bottom:28px">
      <h3>Minimum terms to achieve &lt; 0.1% error</h3>
      <p>Maclaurin consistently needs fewer terms across the full 1°–30° range. Taylor only wins at its expansion point (10°).</p>
      <div class="table-wrap" id="p6table"></div>
    </div>

    <div class="grid-2">
      <div class="chart-card">
        <h3>Convergence — % error vs. terms (Maclaurin)</h3>
        <p>Log-scale. Red dashed line = 0.1% threshold. Each curve is a different angle.</p>
        <div class="chart-wrap" style="height:280px">
          <canvas id="convMacChart"></canvas>
        </div>
      </div>
      <div class="chart-card">
        <h3>Convergence — % error vs. terms (Taylor, a=10°)</h3>
        <p>Taylor at 10° converges to zero at 10° with just 1 term, but struggles far from that point.</p>
        <div class="chart-wrap" style="height:280px">
          <canvas id="convTayChart"></canvas>
        </div>
      </div>
    </div>

    <div class="chart-card">
      <h3>Small-angle approximation: sin(θ) ≈ θ</h3>
      <p>The 1-term approximation. Critical angle where 0.1% is breached shown in amber.</p>
      <div class="chart-wrap" style="height:280px">
        <canvas id="smallAngleChart"></canvas>
      </div>
    </div>

    <div class="callout">
      <strong>Critical angle for sin(θ) ≈ θ:</strong> approximately 5°. Beyond this angle the single-term small-angle approximation exceeds the 0.1% engineering tolerance. Adding the second term (−θ³/6) extends validity to ~30°.
    </div>
  </section>

  <!-- ══════════════════════════════════════════════════════════════ -->
  <!-- PART 7 -->
  <!-- ══════════════════════════════════════════════════════════════ -->
  <section id="s7" class="section">
    <div class="section-title">Part 7</div>
    <h2>Final Engineering Recommendation</h2>
    <p class="section-desc">
      Selecting the best approximation strategy for y = 20·sin(θ) with &lt; 0.1% error across 1°–30°. Decision supported by the numerical evidence in Parts 1–6.
    </p>

    <div class="rec-grid">
      <div class="rec-card">
        <div class="scenario">θ &lt; 5°</div>
        <div class="method">Maclaurin, N = 2</div>
        <div class="detail">2 terms → &lt; 0.001% error. Even 1 term suffices for &lt; 0.1% below 4°.</div>
      </div>
      <div class="rec-card">
        <div class="scenario">θ ≤ 15°</div>
        <div class="method">Maclaurin, N = 3</div>
        <div class="detail">3 terms → &lt; 0.0001% error across this range. Essentially exact.</div>
      </div>
      <div class="rec-card">
        <div class="scenario">θ ≤ 30°</div>
        <div class="method">Maclaurin, N = 4</div>
        <div class="detail">4 terms → &lt; 0.001% everywhere. Meets tolerance with wide margin.</div>
      </div>
      <div class="rec-card">
        <div class="scenario">Production</div>
        <div class="method">Exact math.sin()</div>
        <div class="detail">One hardware-optimised call. Zero truncation error. Always use this in real software.</div>
      </div>
    </div>

    <div class="verdict-box">
      <h3>Engineering Verdict</h3>
      <p>
        For manual or educational computation, use the <strong>Maclaurin series with N = 4 terms</strong>. This requires just 4 multiplications and 4 additions, is fully transparent mathematically, and achieves &lt; 0.001% error across the entire 1°–30° range without pre-computing any auxiliary values.
      </p>
      <ul>
        <li><strong>Terms required:</strong> N = 4 (N = 2 for θ &lt; 5°)</li>
        <li><strong>% error at 30° (N=4):</strong> 0.000002% — far below 0.1% requirement</li>
        <li><strong>Convergence:</strong> Valid for all real θ; error shrinks as θ²/(2n(2n+1)) per added term</li>
        <li><strong>vs. Taylor (a=10°):</strong> Taylor wins near 10° with fewer terms, but requires pre-computing sin(10°) and cos(10°), and performs worse at 1° or 30°. Not worth the complexity for a wide angle range.</li>
        <li><strong>Production code:</strong> Use math.sin() — there is no speed advantage to a truncated series on modern hardware, and accuracy is non-negotiable in structural calculations.</li>
      </ul>
    </div>

    <div class="chart-card">
      <h3>Error comparison — all N values, Maclaurin vs. Taylor</h3>
      <p>Full error landscape by angle. Amber dashed line marks the 0.1% engineering threshold.</p>
      <div class="tabs" style="margin-bottom:16px">
        <button class="tab-btn active" onclick="switchErrTab(1,this)">N = 1</button>
        <button class="tab-btn" onclick="switchErrTab(2,this)">N = 2</button>
        <button class="tab-btn" onclick="switchErrTab(3,this)">N = 3</button>
        <button class="tab-btn" onclick="switchErrTab(4,this)">N = 4</button>
      </div>
      <div class="chart-wrap" style="height:300px">
        <canvas id="errCompChart"></canvas>
      </div>
    </div>

    <div class="callout">
      <strong>Mathematical Progression Complete:</strong>&nbsp;
      Geometric Series → Power Series → Maclaurin (a=0) → Taylor (a=10°) → Engineering Application y = L·sin(θ) → Error Analysis → Engineering Decision.
    </div>
  </section>

</main>

<script>
// ── Embedded data ──────────────────────────────────────────────────────────
const D = {"geo": [{"x": 0.5, "exact": 2.0, "terms": [{"N": 2, "approx": 1.75, "pct": 12.5}, {"N": 5, "approx": 1.96875, "pct": 1.5625}, {"N": 10, "approx": 1.99902344, "pct": 0.048828}, {"N": 20, "approx": 1.99999905, "pct": 4.8e-05}, {"N": 50, "approx": 2.0, "pct": 0.0}]}, {"x": 0.8, "exact": 5.0, "terms": [{"N": 2, "approx": 2.44, "pct": 51.2}, {"N": 5, "approx": 3.68928, "pct": 26.2144}, {"N": 10, "approx": 4.57050327, "pct": 8.589935}, {"N": 20, "approx": 4.95388314, "pct": 0.922337}, {"N": 50, "approx": 4.99994291, "pct": 0.001142}]}, {"x": 0.9, "exact": 10.0, "terms": [{"N": 2, "approx": 2.71, "pct": 72.9}, {"N": 5, "approx": 4.68559, "pct": 53.1441}, {"N": 10, "approx": 6.86189404, "pct": 31.38106}, {"N": 20, "approx": 8.90581011, "pct": 10.941899}, {"N": 50, "approx": 9.95361602, "pct": 0.46384}]}], "mac3": [{"N": 1, "approx": 0.1745329252, "pct": 0.5095058}, {"N": 2, "approx": 0.173646829, "pct": 0.0007766}, {"N": 3, "approx": 0.1736481786, "pct": 6e-07}, {"N": 4, "approx": 0.1736481777, "pct": 0.0}], "part4": {"1": [{"deg": 1, "exact": 0.349048, "approx": 0.349066, "abs_err": 1.772e-05, "pct": 0.005077}, {"deg": 2, "exact": 0.69799, "approx": 0.698132, "abs_err": 0.00014177, "pct": 0.020311}, {"deg": 5, "exact": 1.743115, "approx": 1.745329, "abs_err": 0.0022144, "pct": 0.127037}, {"deg": 10, "exact": 3.472964, "approx": 3.490659, "abs_err": 0.01769495, "pct": 0.509506}, {"deg": 15, "exact": 5.176381, "approx": 5.235988, "abs_err": 0.05960685, "pct": 1.151516}, {"deg": 20, "exact": 6.840403, "approx": 6.981317, "abs_err": 0.14091414, "pct": 2.060027}, {"deg": 30, "exact": 10.0, "approx": 10.471976, "abs_err": 0.47197551, "pct": 4.719755}], "2": [{"deg": 1, "exact": 0.349048, "approx": 0.349048, "abs_err": 0.0, "pct": 0.0}, {"deg": 2, "exact": 0.69799, "approx": 0.69799, "abs_err": 1e-08, "pct": 1e-06}, {"deg": 5, "exact": 1.743115, "approx": 1.743114, "abs_err": 8.4e-07, "pct": 4.8e-05}, {"deg": 10, "exact": 3.472964, "approx": 3.472937, "abs_err": 2.697e-05, "pct": 0.000777}, {"deg": 15, "exact": 5.176381, "approx": 5.176176, "abs_err": 0.00020464, "pct": 0.003953}, {"deg": 20, "exact": 6.840403, "approx": 6.839542, "abs_err": 0.00086124, "pct": 0.012591}, {"deg": 30, "exact": 10.0, "approx": 9.993484, "abs_err": 0.00651641, "pct": 0.065164}], "3": [{"deg": 1, "exact": 0.349048, "approx": 0.349048, "abs_err": 0.0, "pct": 0.0}, {"deg": 2, "exact": 0.69799, "approx": 0.69799, "abs_err": 0.0, "pct": 0.0}, {"deg": 5, "exact": 1.743115, "approx": 1.743115, "abs_err": 0.0, "pct": 0.0}, {"deg": 10, "exact": 3.472964, "approx": 3.472964, "abs_err": 2e-08, "pct": 1e-06}, {"deg": 15, "exact": 5.176381, "approx": 5.176381, "abs_err": 3.3e-07, "pct": 6e-06}, {"deg": 20, "exact": 6.840403, "approx": 6.840405, "abs_err": 2.5e-06, "pct": 3.7e-05}, {"deg": 30, "exact": 10.0, "approx": 10.000043, "abs_err": 4.265e-05, "pct": 0.000427}], "4": [{"deg": 1, "exact": 0.349048, "approx": 0.349048, "abs_err": 0.0, "pct": 0.0}, {"deg": 2, "exact": 0.69799, "approx": 0.69799, "abs_err": 0.0, "pct": 0.0}, {"deg": 5, "exact": 1.743115, "approx": 1.743115, "abs_err": 0.0, "pct": 0.0}, {"deg": 10, "exact": 3.472964, "approx": 3.472964, "abs_err": 0.0, "pct": 0.0}, {"deg": 15, "exact": 5.176381, "approx": 5.176381, "abs_err": 0.0, "pct": 0.0}, {"deg": 20, "exact": 6.840403, "approx": 6.840403, "abs_err": 0.0, "pct": 0.0}, {"deg": 30, "exact": 10.0, "approx": 10.0, "abs_err": 1.6e-07, "pct": 2e-06}]}, "part5": {"1": [{"deg": 1, "exact": 0.01745241, "mac": 0.01745329, "mac_pct": 0.005077, "tay": 0.17364818, "tay_pct": 894.981284}, {"deg": 2, "exact": 0.0348995, "mac": 0.03490659, "mac_pct": 0.020311, "tay": 0.17364818, "tay_pct": 397.566424}, {"deg": 5, "exact": 0.08715574, "mac": 0.08726646, "mac_pct": 0.127037, "tay": 0.17364818, "tay_pct": 99.23894}, {"deg": 10, "exact": 0.17364818, "mac": 0.17453293, "mac_pct": 0.509506, "tay": 0.17364818, "tay_pct": 0.0}, {"deg": 15, "exact": 0.25881905, "mac": 0.26179939, "mac_pct": 1.151516, "tay": 0.17364818, "tay_pct": 32.907496}, {"deg": 20, "exact": 0.34202014, "mac": 0.34906585, "mac_pct": 2.060027, "tay": 0.17364818, "tay_pct": 49.228669}, {"deg": 30, "exact": 0.5, "mac": 0.52359878, "mac_pct": 4.719755, "tay": 0.17364818, "tay_pct": 65.270364}], "2": [{"deg": 1, "exact": 0.01745241, "mac": 0.01745241, "mac_pct": 0.0, "tay": 0.01895494, "tay_pct": 8.609306}, {"deg": 2, "exact": 0.0348995, "mac": 0.0348995, "mac_pct": 1e-06, "tay": 0.03614308, "tay_pct": 3.563314}, {"deg": 5, "exact": 0.08715574, "mac": 0.0871557, "mac_pct": 4.8e-05, "tay": 0.08770749, "tay_pct": 0.633058}, {"deg": 10, "exact": 0.17364818, "mac": 0.17364683, "mac_pct": 0.000777, "tay": 0.17364818, "tay_pct": 0.0}, {"deg": 15, "exact": 0.25881905, "mac": 0.25880881, "mac_pct": 0.003953, "tay": 0.25958887, "tay_pct": 0.297436}, {"deg": 20, "exact": 0.34202014, "mac": 0.34197708, "mac_pct": 0.012591, "tay": 0.34552956, "tay_pct": 1.026083}, {"deg": 30, "exact": 0.5, "mac": 0.49967418, "mac_pct": 0.065164, "tay": 0.51741093, "tay_pct": 3.482187}], "3": [{"deg": 1, "exact": 0.01745241, "mac": 0.01745241, "mac_pct": 0.0, "tay": 0.01681264, "tay_pct": 3.665783}, {"deg": 2, "exact": 0.0348995, "mac": 0.0348995, "mac_pct": 0.0, "tay": 0.0344504, "tay_pct": 1.286843}, {"deg": 5, "exact": 0.08715574, "mac": 0.08715574, "mac_pct": 0.0, "tay": 0.08704629, "tay_pct": 0.125588}, {"deg": 10, "exact": 0.17364818, "mac": 0.17364818, "mac_pct": 1e-06, "tay": 0.17364818, "tay_pct": 0.0}, {"deg": 15, "exact": 0.25881905, "mac": 0.25881906, "mac_pct": 6e-06, "tay": 0.25892766, "tay_pct": 0.041967}, {"deg": 20, "exact": 0.34202014, "mac": 0.34202027, "mac_pct": 3.7e-05, "tay": 0.34288474, "tay_pct": 0.252792}, {"deg": 30, "exact": 0.5, "mac": 0.50000213, "mac_pct": 0.000427, "tay": 0.50683168, "tay_pct": 1.366336}], "4": [{"deg": 1, "exact": 0.01745241, "mac": 0.01745241, "mac_pct": 0.0, "tay": 0.01744879, "tay_pct": 0.020725}, {"deg": 2, "exact": 0.0348995, "mac": 0.0348995, "mac_pct": 0.0, "tay": 0.03489718, "tay_pct": 0.006627}, {"deg": 5, "exact": 0.08715574, "mac": 0.08715574, "mac_pct": 0.0, "tay": 0.08715536, "tay_pct": 0.000434}, {"deg": 10, "exact": 0.17364818, "mac": 0.17364818, "mac_pct": 0.0, "tay": 0.17364818, "tay_pct": 0.0}, {"deg": 15, "exact": 0.25881905, "mac": 0.25881905, "mac_pct": 0.0, "tay": 0.25881858, "tay_pct": 0.000178}, {"deg": 20, "exact": 0.34202014, "mac": 0.34202014, "mac_pct": 0.0, "tay": 0.34201211, "tay_pct": 0.002349}, {"deg": 30, "exact": 0.5, "mac": 0.49999999, "mac_pct": 2e-06, "tay": 0.49985061, "tay_pct": 0.029879}]}, "part6_min": [{"deg": 1, "mac_n": 1, "mac_pct": 0.005077, "tay_n": 4, "tay_pct": 0.020725}, {"deg": 2, "mac_n": 1, "mac_pct": 0.020311, "tay_n": 4, "tay_pct": 0.006627}, {"deg": 5, "mac_n": 2, "mac_pct": 4.8e-05, "tay_n": 4, "tay_pct": 0.000434}, {"deg": 10, "mac_n": 2, "mac_pct": 0.000777, "tay_n": 1, "tay_pct": 0.0}, {"deg": 15, "mac_n": 2, "mac_pct": 0.003953, "tay_n": 3, "tay_pct": 0.041967}, {"deg": 20, "mac_n": 2, "mac_pct": 0.012591, "tay_n": 4, "tay_pct": 0.002349}, {"deg": 30, "mac_n": 2, "mac_pct": 0.065164, "tay_n": 4, "tay_pct": 0.029879}], "small_angle": [{"deg": 1, "pct": 0.005077}, {"deg": 2, "pct": 0.020311}, {"deg": 3, "pct": 0.045707}, {"deg": 4, "pct": 0.081278}, {"deg": 5, "pct": 0.127037}, {"deg": 6, "pct": 0.183005}, {"deg": 7, "pct": 0.249205}, {"deg": 8, "pct": 0.325666}, {"deg": 9, "pct": 0.41242}, {"deg": 10, "pct": 0.509506}, {"deg": 15, "pct": 1.151516}, {"deg": 20, "pct": 2.060027}, {"deg": 25, "pct": 3.245021}, {"deg": 30, "pct": 4.719755}], "conv_mac": {"5": [0.127036783, 4.8382e-05, 9e-09, 1e-09, 1e-09, 1e-09, 1e-09], "10": [0.509505798, 0.000776641, 5.63e-07, 1e-09, 1e-09, 1e-09, 1e-09], "20": [2.060026934, 0.012590537, 3.6571e-05, 6.2e-08, 1e-09, 1e-09, 1e-09], "30": [4.71975512, 0.065164121, 0.000426518, 1.626e-06, 4e-09, 1e-09, 1e-09]}, "conv_tay": {"5": [99.238939618, 0.633057508, 0.125588138, 0.000433683, 4.7769e-05, 1.14e-07, 9e-09], "10": [1e-09, 1e-09, 1e-09, 1e-09, 1e-09, 1e-09, 1e-09], "20": [49.228669406, 1.026083493, 0.252791907, 0.002349313, 0.000386328, 2.274e-06, 2.81e-07], "30": [65.270364467, 3.48218669, 1.366336297, 0.029878685, 0.008394523, 0.000111706, 2.4446e-05]}, "fine_degs": [0.4,0.8,1.2,1.6,2.0,2.4,2.8,3.2,3.6,4.0,4.4,4.8,5.2,5.6,6.0,6.4,6.8,7.2,7.6,8.0,8.4,8.8,9.2,9.6,10.0,10.4,10.8,11.2,11.6,12.0,12.4,12.8,13.2,13.6,14.0,14.4,14.8,15.2,15.6,16.0,16.4,16.8,17.2,17.6,18.0,18.4,18.8,19.2,19.6,20.0,20.4,20.8,21.2,21.6,22.0,22.4,22.8,23.2,23.6,24.0,24.4,24.8,25.2,25.6,26.0,26.4,26.8,27.2,27.6,28.0,28.4,28.8,29.2,29.6,30.0,30.4,30.8,31.2,31.6,32.0,32.4,32.8], "fine_exact": [0.00698126,0.01396218,0.02094242,0.02792164,0.0348995,0.04187565,0.04884977,0.0558215,0.06279052,0.06975647,0.07671903,0.08367784,0.09063258,0.0975829,0.10452846,0.11146893,0.11840397,0.12533323,0.13225639,0.1391731,0.14608303,0.15298584,0.15988119,0.16676875,0.17364818,0.18051915,0.18738131,0.19423435,0.20107792,0.20791169,0.21473533,0.2215485,0.22835087,0.23514211,0.2419219,0.24868989,0.25544576,0.26218918,0.26891982,0.27563736,0.28234146,0.2890318,0.29570805,0.30236989,0.30901699,0.31564904,0.3222657,0.32886665,0.33545157,0.34202014,0.34857205,0.35510696,0.36162457,0.36812455,0.37460659,0.38107038,0.38751559,0.39394191,0.40034903,0.40673664,0.41310443,0.41945208,0.42577929,0.43208575,0.43837115,0.44463518,0.45087754,0.45709793,0.46329604,0.46947156,0.47562421,0.48175367,0.48785966,0.49394187,0.5,0.50603376,0.51204286,0.51802701,0.52398591,0.52991926,0.53582679,0.54170821], "fine_mac": {"1":[0.00698132,0.01396263,0.02094395,0.02792527,0.03490659,0.0418879,0.04886922,0.05585054,0.06283185,0.06981317,0.07679449,0.0837758,0.09075712,0.09773844,0.10471976,0.11170107,0.11868239,0.12566371,0.13264502,0.13962634,0.14660766,0.15358897,0.16057029,0.16755161,0.17453293,0.18151424,0.18849556,0.19547688,0.20245819,0.20943951,0.21642083,0.22340214,0.23038346,0.23736478,0.2443461,0.25132741,0.25830873,0.26529005,0.27227136,0.27925268,0.286234,0.29321531,0.30019663,0.30717795,0.31415927,0.32114058,0.3281219,0.33510322,0.34208453,0.34906585,0.35604717,0.36302848,0.3700098,0.37699112,0.38397244,0.39095375,0.39793507,0.40491639,0.4118977,0.41887902,0.42586034,0.43284165,0.43982297,0.44680429,0.45378561,0.46076692,0.46774824,0.47472956,0.48171087,0.48869219,0.49567351,0.50265482,0.50963614,0.51661746,0.52359878,0.53058009,0.53756141,0.54454273,0.55152404,0.55850536,0.56548668,0.57246799],"3":[0.00698126,0.01396218,0.02094242,0.02792164,0.0348995,0.04187565,0.04884977,0.0558215,0.06279052,0.06975647,0.07671903,0.08367784,0.09063258,0.0975829,0.10452846,0.11146893,0.11840397,0.12533323,0.13225639,0.1391731,0.14608303,0.15298584,0.15988119,0.16676875,0.17364818,0.18051915,0.18738132,0.19423435,0.20107792,0.20791169,0.21473533,0.2215485,0.22835088,0.23514212,0.24192191,0.2486899,0.25544577,0.2621892,0.26891984,0.27563738,0.28234149,0.28903183,0.29570809,0.30236994,0.30901705,0.31564911,0.32226578,0.32886674,0.33545168,0.34202027,0.34857219,0.35510713,0.36162476,0.36812477,0.37460684,0.38107065,0.3875159,0.39394226,0.40034943,0.40673709,0.41310493,0.41945265,0.42577992,0.43208645,0.43837193,0.44463605,0.45087851,0.457099,0.46329723,0.46947288,0.47562566,0.48175528,0.48786142,0.49394381,0.50000213,0.5060361,0.51204543,0.51802981,0.52398897,0.52992261,0.53583045,0.54171219]}, "fine_tay": {"3":[0.0062046,0.01327874,0.02034442,0.02740164,0.0344504,0.04149069,0.04852251,0.05554588,0.06256078,0.06956722,0.07656519,0.0835547,0.09053575,0.09750834,0.10447246,0.11142811,0.11837531,0.12531404,0.13224431,0.13916611,0.14607945,0.15298433,0.15988074,0.16676869,0.17364818,0.1805192,0.18738176,0.19423586,0.20108149,0.20791866,0.21474737,0.22156761,0.22837939,0.23518271,0.24197756,0.24876395,0.25554187,0.26231134,0.26907234,0.27582487,0.28256894,0.28930455,0.2960317,0.30275038,0.3094606,0.31616236,0.32285565,0.32954048,0.33621684,0.34288474,0.34954418,0.35619516,0.36283767,0.36947172,0.3760973,0.38271442,0.38932308,0.39592327,0.40251501,0.40909827,0.41567308,0.42223942,0.4287973,0.43534671,0.44188766,0.44842015,0.45494417,0.46145973,0.46796683,0.47446546,0.48095563,0.48743734,0.49391058,0.50037536,0.50683168,0.51327953,0.51971892,0.52614985,0.53257231,0.53898631,0.54539185,0.55178892]}, "fine_mac_pct": {"1":[0.000859,0.003223,0.007306,0.013001,0.020315,0.029253,0.039816,0.052023,0.065822,0.081283,0.098359,0.117068,0.137412,0.159393,0.183012,0.208255,0.235144,0.263681,0.293846,0.325666,0.359131,0.394239,0.431008,0.469428,0.509507,0.551238,0.594643,0.639707,0.686435,0.734841,0.78492,0.836675,0.890117,0.945245,1.002059,1.060566,1.120774,1.182684,1.246297,1.311622,1.378664,1.447422,1.517909,1.590125,1.664077,1.739761,1.817196,1.896383,1.977323,2.060028,2.144498,2.230742,2.318767,2.408579,2.500183,2.593581,2.68879,2.785812,2.88465,2.985317,3.087817,3.192157,3.298347,3.406393,3.516303,3.628084,3.741748,3.857298,3.974744,4.094099,4.215366,4.338555,4.463677,4.590741,4.719756,4.85073,4.983675,5.118598,5.25551,5.394426,5.53535,5.678293],"2":[1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1.6e-5,1.4e-5,2.6e-5,3.6e-5,5.5e-5,7.2e-5,9.6e-5,0.000126,0.000169,0.000207,0.000257,0.000316,0.00039,0.000471,0.000557,0.00066,0.000777,0.000914,0.001057,0.001225,0.001407,0.001611,0.001839,0.00209,0.002365,0.002666,0.002997,0.003358,0.003746,0.004169,0.00463,0.005126,0.00566,0.006238,0.006855,0.007521,0.008233,0.008997,0.009812,0.010679,0.011605,0.01259,0.013638,0.01475,0.015931,0.017179,0.018502,0.019902,0.021377,0.022937,0.024579,0.026309,0.028133,0.030049,0.032064,0.034181,0.036401,0.038728,0.041169,0.043724,0.046398,0.049194,0.052119,0.055173,0.058363,0.061693,0.065164,0.068782,0.072554,0.076482,0.080571,0.084824,0.089247,0.093848],"3":[1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,5.3e-6,1e-9,1e-9,1e-9,1e-9,1e-9,4.4e-6,4.3e-6,4.1e-6,4.0e-6,3.9e-6,7.6e-6,7.4e-6,7.3e-6,1.06e-5,1.04e-5,1.35e-5,1.65e-5,1.94e-5,2.22e-5,2.48e-5,2.74e-5,3.28e-5,3.8e-5,4.02e-5,4.79e-5,5.25e-5,5.98e-5,6.67e-5,7.09e-5,8.0e-5,8.88e-5,9.99e-5,0.000111,0.000121,0.000136,0.000148,0.000162,0.000178,0.000196,0.000215,0.000234,0.000257,0.000281,0.000305,0.000334,0.000361,0.000393,0.000426,0.000462,0.000502,0.000541,0.000584,0.000632,0.000683,0.000735],"4":[1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,2.3e-6,1e-9,1e-9,2.2e-6,2.2e-6,1e-9,2.1e-6,1e-9,2.1e-6,2.0e-6,2.0e-6,2.0e-6,2.0e-6,1.9e-6,3.8e-6,1.9e-6,1.9e-6,3.7e-6]}, "fine_tay_pct": {"1":[2387,1144,729,522,398,315,255,211,177,149,126,108,92,78,66,56,47,39,31,25,19,14,8.6,4.1,1e-9,3.8,7.3,10.6,13.6,16.5,19.1,21.6,24.0,26.2,28.2,30.2,32.0,33.8,35.4,37.0,38.5,39.9,41.3,42.6,43.8,45.0,46.1,47.2,48.2,49.2,50.2,51.1,52.0,52.8,53.6,54.4,55.2,55.9,56.6,57.3,58.0,58.6,59.2,59.8,60.4,60.9,61.5,62.0,62.5,63.0,63.5,64.0,64.4,64.8,65.3,65.7,66.1,66.5,66.9,67.2,67.6,67.9],"2":[23.8,11.1,6.9,4.8,3.6,2.7,2.1,1.7,1.4,1.1,0.88,0.71,0.57,0.45,0.35,0.27,0.2,0.15,0.11,0.071,0.044,0.024,0.01,0.0025,1e-9,0.0024,0.0093,0.02,0.035,0.054,0.077,0.102,0.131,0.163,0.198,0.236,0.276,0.319,0.365,0.413,0.464,0.517,0.573,0.631,0.691,0.754,0.819,0.886,0.955,1.026,1.1,1.175,1.253,1.333,1.415,1.499,1.585,1.673,1.763,1.855,1.949,2.046,2.144,2.244,2.347,2.451,2.558,2.666,2.776,2.889,3.004,3.12,3.239,3.359,3.482,3.607,3.734,3.863,3.994,4.127,4.262,4.399],"3":[11.1,4.9,2.9,1.9,1.3,0.92,0.67,0.49,0.37,0.27,0.2,0.15,0.107,0.076,0.054,0.037,0.024,0.015,0.009,0.005,0.0025,0.001,0.00028,3.6e-5,1e-9,2.8e-5,0.00024,0.00078,0.00178,0.00335,0.00561,0.00863,0.01249,0.01727,0.02301,0.02978,0.03762,0.04659,0.05672,0.06803,0.08057,0.09437,0.10945,0.12584,0.14356,0.16262,0.18306,0.20489,0.22813,0.25279,0.27889,0.30644,0.33546,0.36595,0.39794,0.43143,0.46643,0.50296,0.54102,0.58063,0.62179,0.66452,0.70882,0.75470,0.80217,0.85125,0.90194,0.95424,1.00816,1.06373,1.12099,1.17979,1.24030,1.30248,1.36634,1.43187,1.49910,1.56803,1.63867,1.71102,1.78510,1.86091],"4":[0.066,0.028,0.016,0.01,0.0066,0.0045,0.0032,0.0022,0.00156,0.00109,0.00077,0.000526,0.000353,0.000236,0.000144,8.97e-5,5.91e-5,3.19e-5,1.51e-5,7.2e-6,6.8e-6,6.5e-6,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,1e-9,4.8e-6,1.4e-5,2.3e-5,3.1e-5,5.1e-5,7.9e-5,0.000113,0.000153,0.000206,0.000271,0.000356,0.00045,0.000564,0.000697,0.00085,0.00103,0.001236,0.001468,0.001727,0.002021,0.002348,0.002714,0.003117,0.003564,0.004056,0.004591,0.00518,0.005822,0.006516,0.007269,0.008084,0.008961,0.009908,0.010926,0.012016,0.013185,0.014432,0.015765,0.017185,0.018697,0.020299,0.022005,0.023809,0.025721,0.027744,0.029878,0.032132,0.034509,0.037012,0.039646,0.042414,0.045322,0.048377]}};

// ── Chart defaults ──────────────────────────────────────────────────────────
Chart.defaults.color = '#94a3b8';
Chart.defaults.font.family = "'IBM Plex Mono', monospace";
Chart.defaults.font.size = 11;

const PALETTE = {
  amber:   '#f59e0b',
  amber2:  '#fcd34d',
  steel:   '#3b82c4',
  sky:     '#93c5fd',
  success: '#34d399',
  danger:  '#f87171',
  purple:  '#a78bfa',
  pink:    '#f472b6',
  muted:   '#64748b',
  navy3:   '#1a2f50',
};

const ANGLE_COLORS = ['#93c5fd','#34d399','#f59e0b','#f87171'];

function gridCfg() {
  return { color: 'rgba(147,197,253,0.08)', lineWidth: 1 };
}
function tooltipCfg() {
  return {
    backgroundColor: '#0f1f3d',
    borderColor: 'rgba(147,197,253,0.2)',
    borderWidth: 1,
    titleColor: '#f0f6ff',
    bodyColor: '#94a3b8',
    padding: 10,
  };
}

// ── Navigation ─────────────────────────────────────────────────────────────
function showSection(id) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('visible'));
  document.querySelectorAll('nav a').forEach(a => a.classList.remove('active'));
  document.getElementById(id).classList.add('visible');
  document.getElementById('nav-' + id).classList.add('active');
  return false;
}

// ── Tab switching ──────────────────────────────────────────────────────────
function switchTab(group, panelId, btn) {
  document.querySelectorAll(`[id^="${group}-"]`).forEach(p => p.classList.remove('active'));
  btn.closest('.tabs').querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`${group}-${panelId}`).classList.add('active');
  btn.classList.add('active');
}

// ── Colour by % error ──────────────────────────────────────────────────────
function pctClass(v) {
  if (v < 0.001) return 'good';
  if (v < 0.1)   return 'ok';
  return 'bad';
}

function fmt(v, decimals=6) {
  if (v === 0) return '0';
  if (Math.abs(v) < 1e-7) return v.toExponential(2);
  return v.toFixed(decimals);
}

// ── Build tables ───────────────────────────────────────────────────────────
function buildGeoTable(containerId, xIdx) {
  const g = D.geo[xIdx];
  let h = `<table><thead><tr>
    <th>N terms</th><th>Partial Sum S_N</th><th>Exact 1/(1-x)</th><th>Abs Error</th><th>% Error</th>
  </tr></thead><tbody>`;
  g.terms.forEach(t => {
    const cls = pctClass(t.pct);
    const err = Math.abs(t.approx - g.exact);
    h += `<tr>
      <td class="num">${t.N}</td>
      <td class="num">${t.approx.toFixed(8)}</td>
      <td class="num">${g.exact.toFixed(8)}</td>
      <td class="num">${err.toExponential(3)}</td>
      <td class="num ${cls}">${t.pct.toFixed(5)}%</td>
    </tr>`;
  });
  h += '</tbody></table>';
  document.getElementById(containerId).innerHTML = h;
}

function buildMac3Table() {
  const exact = 0.1736481777;
  let h = `<table><thead><tr>
    <th>N terms</th><th>Terms included</th><th>Approximation</th><th>Abs Error</th><th>% Error</th>
  </tr></thead><tbody>`;
  const termLabels = ['θ','−θ³/3!','+ θ⁵/5!','−θ⁷/7!'];
  D.mac3.forEach((r,i) => {
    const cls = pctClass(r.pct);
    const err = Math.abs(r.approx - exact);
    const terms = termLabels.slice(0,r.N).join(' ');
    h += `<tr>
      <td class="num">${r.N}</td>
      <td style="color:var(--sky);font-size:11px">${terms}</td>
      <td class="num">${r.approx.toFixed(10)}</td>
      <td class="num">${err < 1e-13 ? '< 1e-13' : err.toExponential(3)}</td>
      <td class="num ${cls}">${r.pct < 1e-6 ? '~0' : r.pct.toFixed(7)}%</td>
    </tr>`;
  });
  h += '</tbody></table>';
  document.getElementById('mac3table').innerHTML = h;
}

function buildP4Table(containerId, N) {
  const rows = D.part4[String(N)];
  let h = `<table><thead><tr>
    <th>Angle (°)</th><th>Exact y (m)</th><th>Approx y (m)</th><th>Abs Error (m)</th><th>% Error</th>
  </tr></thead><tbody>`;
  rows.forEach(r => {
    const cls = pctClass(r.pct);
    h += `<tr>
      <td class="num">${r.deg}°</td>
      <td class="num">${r.exact.toFixed(6)}</td>
      <td class="num">${r.approx.toFixed(6)}</td>
      <td class="num">${r.abs_err < 1e-9 ? '< 1e-9' : r.abs_err.toExponential(3)}</td>
      <td class="num ${cls}">${r.pct < 1e-6 ? '~0' : r.pct.toFixed(6)}%</td>
    </tr>`;
  });
  h += '</tbody></table>';
  document.getElementById(containerId).innerHTML = h;
}

function buildP5Table(containerId, N) {
  const rows = D.part5[String(N)];
  let h = `<table><thead><tr>
    <th>Angle</th><th>Exact sin</th>
    <th>Maclaurin</th><th>Mac %Err</th>
    <th>Taylor (a=10°)</th><th>Tay %Err</th>
  </tr></thead><tbody>`;
  rows.forEach(r => {
    const mc = pctClass(r.mac_pct), tc = pctClass(r.tay_pct);
    h += `<tr>
      <td class="num">${r.deg}°</td>
      <td class="num">${r.exact.toFixed(8)}</td>
      <td class="num">${r.mac.toFixed(8)}</td>
      <td class="num ${mc}">${r.mac_pct < 1e-6 ? '~0' : r.mac_pct.toFixed(6)}%</td>
      <td class="num">${r.tay.toFixed(8)}</td>
      <td class="num ${tc}">${r.tay_pct < 1e-6 ? '~0' : r.tay_pct.toFixed(6)}%</td>
    </tr>`;
  });
  h += '</tbody></table>';
  document.getElementById(containerId).innerHTML = h;
}

function buildP6Table() {
  let h = `<table><thead><tr>
    <th>Angle</th>
    <th>Maclaurin: min N</th><th>Mac % err</th>
    <th>Taylor: min N</th><th>Tay % err</th>
    <th>Winner</th>
  </tr></thead><tbody>`;
  D.part6_min.forEach(r => {
    const winner = r.mac_n <= r.tay_n ? 'Maclaurin' : 'Taylor';
    const wc = winner === 'Maclaurin' ? 'good' : 'ok';
    h += `<tr>
      <td class="num">${r.deg}°</td>
      <td class="num">${r.mac_n}</td>
      <td class="num good">${r.mac_pct.toFixed(5)}%</td>
      <td class="num">${r.tay_n}</td>
      <td class="num ok">${r.tay_pct.toFixed(5)}%</td>
      <td class="num ${wc}">${winner}</td>
    </tr>`;
  });
  h += '</tbody></table>';
  document.getElementById('p6table').innerHTML = h;
}

// ── Build charts ───────────────────────────────────────────────────────────
let errCompChartRef = null;

function makeLogChart(canvasId, datasets, xLabel, yLabel, opts={}) {
  const ctx = document.getElementById(canvasId).getContext('2d');
  return new Chart(ctx, {
    type: 'line',
    data: { labels: opts.labels || [1,2,3,4,5,6,7], datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 600 },
      plugins: {
        legend: { position: 'top', labels: { boxWidth: 12, padding: 14 } },
        tooltip: { ...tooltipCfg(),
          callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toExponential(3)}%` }
        },
      },
      scales: {
        x: { title: { display: true, text: xLabel }, grid: gridCfg() },
        y: {
          type: 'logarithmic', title: { display: true, text: yLabel },
          grid: gridCfg(),
          ticks: { callback: v => {
            const log = Math.log10(v);
            if (Number.isInteger(Math.round(log))) return `${v.toExponential(0)}`;
            return null;
          }}
        }
      }
    }
  });
}

function buildGeoChart() {
  const Ns = [2,5,10,20,50];
  const datasets = D.geo.map((g,i) => ({
    label: `x = ${g.x}`,
    data: g.terms.map(t => Math.max(t.pct, 1e-6)),
    borderColor: ANGLE_COLORS[i],
    backgroundColor: 'transparent',
    pointBackgroundColor: ANGLE_COLORS[i],
    tension: 0.3, pointRadius: 5, borderWidth: 2,
  }));
  makeLogChart('geoChart', datasets, 'N (number of terms)', '% Error', { labels: Ns });
}

function buildMac3Chart() {
  const exact = 0.1736481777;
  const data = D.mac3.map(r => Math.max(Math.abs(r.approx - exact)/exact*100, 1e-13));
  const ctx = document.getElementById('mac3chart').getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: ['N=1','N=2','N=3','N=4'],
      datasets: [{
        label: '% Error at θ=10°',
        data,
        backgroundColor: [PALETTE.danger, PALETTE.amber, PALETTE.sky, PALETTE.success],
        borderWidth: 0, borderRadius: 4,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { ...tooltipCfg(),
          callbacks: { label: ctx => `${ctx.parsed.y.toExponential(3)}%` }
        }
      },
      scales: {
        x: { grid: gridCfg() },
        y: { type: 'logarithmic', grid: gridCfg(),
          ticks: { callback: v => Number.isInteger(Math.round(Math.log10(v))) ? `${v.toExponential(0)}%` : null }
        }
      }
    }
  });
}

function buildEngChart() {
  const labels = D.fine_degs.map(d => d.toFixed(1));
  const datasets = [
    { label: 'Exact', data: D.fine_exact.map(v => v*20), borderColor: '#ffffff',
      borderWidth: 2.5, tension: 0.3, pointRadius: 0 },
    { label: 'N=1', data: D.fine_mac['1'].map(v => v*20), borderColor: PALETTE.danger,
      borderWidth: 1.5, borderDash: [6,3], tension: 0.3, pointRadius: 0 },
    { label: 'N=3', data: D.fine_mac['3'].map(v => v*20), borderColor: PALETTE.success,
      borderWidth: 1.5, borderDash: [3,3], tension: 0.3, pointRadius: 0 },
  ];
  const ctx = document.getElementById('engChart').getContext('2d');
  new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top', labels: { boxWidth: 12 } }, tooltip: tooltipCfg() },
      scales: {
        x: { title: { display: true, text: 'θ (degrees)' }, grid: gridCfg(), ticks: { maxTicksLimit: 10 } },
        y: { title: { display: true, text: 'y = 20·sin(θ) (m)' }, grid: gridCfg() }
      }
    }
  });
}

function buildFuncChart() {
  const labels = D.fine_degs.map(d => d.toFixed(1));
  const datasets = [
    { label: 'Exact sin(θ)', data: D.fine_exact, borderColor: '#ffffff', borderWidth: 2.5, tension: 0.3, pointRadius: 0 },
    { label: 'Maclaurin N=3 (a=0°)', data: D.fine_mac['3'], borderColor: PALETTE.steel, borderWidth: 2, borderDash: [6,3], tension: 0.3, pointRadius: 0 },
    { label: 'Taylor N=3 (a=10°)', data: D.fine_tay['3'], borderColor: PALETTE.amber, borderWidth: 2, borderDash: [3,3], tension: 0.3, pointRadius: 0 },
  ];
  const ctx = document.getElementById('funcChart').getContext('2d');
  new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top', labels: { boxWidth: 12 } }, tooltip: tooltipCfg() },
      scales: {
        x: { title: { display: true, text: 'θ (degrees)' }, grid: gridCfg(), ticks: { maxTicksLimit: 10 } },
        y: { title: { display: true, text: 'sin(θ)' }, grid: gridCfg() }
      }
    }
  });
}

function buildErrChart3() {
  const labels = D.fine_degs.map(d => d.toFixed(1));
  const datasets = [
    { label: 'Maclaurin (a=0°)', data: D.fine_mac_pct['3'], borderColor: PALETTE.steel, borderWidth: 2, tension: 0.2, pointRadius: 0 },
    { label: 'Taylor (a=10°)',   data: D.fine_tay_pct['3'], borderColor: PALETTE.amber, borderWidth: 2, tension: 0.2, pointRadius: 0 },
    { label: '0.1% threshold',   data: new Array(labels.length).fill(0.1), borderColor: PALETTE.danger, borderWidth: 1, borderDash:[4,4], pointRadius: 0 },
  ];
  makeLogChart('errChart3', datasets, 'θ (degrees)', '% Error', { labels });
}

function buildConvCharts() {
  const angles = [5,10,20,30];
  const Ns = [1,2,3,4,5,6,7];

  ['mac','tay'].forEach(type => {
    const datasets = angles.map((a,i) => ({
      label: `${a}°`,
      data: D[`conv_${type}`][String(a)].map(v => Math.max(v, 1e-10)),
      borderColor: ANGLE_COLORS[i],
      backgroundColor: 'transparent',
      pointBackgroundColor: ANGLE_COLORS[i],
      tension: 0.3, pointRadius: 4, borderWidth: 2,
    }));
    datasets.push({
      label: '0.1% tol',
      data: new Array(7).fill(0.1),
      borderColor: PALETTE.danger,
      borderDash: [5,4],
      pointRadius: 0, borderWidth: 1.5,
    });
    makeLogChart(`conv${type === 'mac' ? 'Mac' : 'Tay'}Chart`, datasets, 'N (terms)', '% Error', { labels: Ns });
  });
}

function buildSmallAngleChart() {
  const labels = D.small_angle.map(r => r.deg + '°');
  const data   = D.small_angle.map(r => r.pct);
  const ctx = document.getElementById('smallAngleChart').getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '% Error: sin(θ) ≈ θ',
        data,
        backgroundColor: data.map(v => v < 0.1 ? 'rgba(52,211,153,0.7)' : 'rgba(248,113,113,0.7)'),
        borderWidth: 0, borderRadius: 3,
      },{
        label: '0.1% threshold',
        data: new Array(labels.length).fill(0.1),
        type: 'line',
        borderColor: PALETTE.amber,
        borderWidth: 2,
        borderDash: [5,4],
        pointRadius: 0,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top', labels: { boxWidth: 12 } },
        tooltip: { ...tooltipCfg(), callbacks: { label: c => `${c.parsed.y.toFixed(4)}%` }}
      },
      scales: {
        x: { grid: gridCfg() },
        y: { title: { display: true, text: '% Error' }, grid: gridCfg() }
      }
    }
  });
}

// Error comparison chart (Part 7) — dynamic by N
function buildErrCompChart(N) {
  const labels = D.fine_degs.map(d => d.toFixed(1));
  if (errCompChartRef) { errCompChartRef.destroy(); errCompChartRef = null; }
  const datasets = [
    { label: `Maclaurin N=${N} (a=0°)`, data: D.fine_mac_pct[String(N)], borderColor: PALETTE.steel, borderWidth: 2, tension: 0.2, pointRadius: 0 },
    { label: `Taylor N=${N} (a=10°)`,   data: D.fine_tay_pct[String(N)], borderColor: PALETTE.amber, borderWidth: 2, tension: 0.2, pointRadius: 0 },
    { label: '0.1% threshold', data: new Array(labels.length).fill(0.1), borderColor: PALETTE.danger, borderWidth: 1, borderDash:[5,4], pointRadius: 0 },
  ];
  const ctx = document.getElementById('errCompChart').getContext('2d');
  errCompChartRef = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: { legend: { position: 'top', labels: { boxWidth: 12 } }, tooltip: tooltipCfg() },
      scales: {
        x: { title: { display: true, text: 'θ (degrees)' }, grid: gridCfg(), ticks: { maxTicksLimit: 10 } },
        y: { type: 'logarithmic', title: { display: true, text: '% Error' }, grid: gridCfg(),
          ticks: { callback: v => Number.isInteger(Math.round(Math.log10(v))) ? `${v.toExponential(0)}%` : null }
        }
      }
    }
  });
}

function switchErrTab(N, btn) {
  btn.closest('.tabs').querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  buildErrCompChart(N);
}

// ── Init ───────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  // Tables
  buildGeoTable('gt05', 0);
  buildGeoTable('gt08', 1);
  buildGeoTable('gt09', 2);
  buildMac3Table();
  [1,2,3,4].forEach(n => buildP4Table(`p4t${n}`, n));
  [1,2,3,4].forEach(n => buildP5Table(`p5t${n}`, n));
  buildP6Table();

  // Charts
  buildGeoChart();
  buildMac3Chart();
  buildEngChart();
  buildFuncChart();
  buildErrChart3();
  buildConvCharts();
  buildSmallAngleChart();
  buildErrCompChart(1);
});

// Prevent default on nav links
document.querySelectorAll('nav a').forEach(a => {
  a.addEventListener('click', e => e.preventDefault());
});
</script>
</body>
</html>'''


def generate_dashboard(output_path=None):
  output_file = Path(output_path) if output_path else Path(__file__).with_name("series_dashboard.html")
  dashboard_data = json.dumps(build_dashboard_data(), separators=(",", ":"))
  html = re.sub(
    r"const D = .*?;\r?\n(?=// ── Chart defaults)",
    f"const D = {dashboard_data};\n",
    HTML_TEMPLATE,
    count=1,
    flags=re.DOTALL,
  )
  output_file.write_text(html, encoding="utf-8")
  print(f"Dashboard generated: {output_file.resolve()}")
  return output_file


if __name__ == "__main__":
  generate_dashboard()