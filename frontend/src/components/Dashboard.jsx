import { useState, useEffect, useRef } from "react";
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, ArcElement, Tooltip, Legend, Filler,
} from "chart.js";
import { Line, Bar, Doughnut } from "react-chartjs-2";

ChartJS.register(
  CategoryScale, LinearScale, PointElement, LineElement,
  BarElement, ArcElement, Tooltip, Legend, Filler
);

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";
const api = (path) => fetch(`${API_URL}${path}`).then((r) => r.json());

// ── Colour tokens ─────────────────────────────────────────────────────────────
const C = {
  p1: "#e53e3e", p1bg: "#fff5f5", p1border: "#fed7d7",
  p2: "#d69e2e", p2bg: "#fffff0", p2border: "#fefcbf",
  p3: "#38a169", p3bg: "#f0fff4", p3border: "#c6f6d5",
  ink: "#1a202c", muted: "#718096", border: "#e2e8f0",
  surface: "#ffffff", bg: "#f7fafc",
  accent: "#3182ce",
};

// ── Tiny helpers ──────────────────────────────────────────────────────────────
const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);

const DeltaBadge = ({ value, invert = false }) => {
  if (value === 0) return <span style={styles.deltaNeutral}>→ 0</span>;
  const up = value > 0;
  const good = invert ? !up : up;
  return (
    <span style={good ? styles.deltaGood : styles.deltaBad}>
      {up ? "▲" : "▼"} {Math.abs(value)}
    </span>
  );
};

const Spinner = () => (
  <div style={styles.spinnerWrap}>
    <div style={styles.spinner} />
    <p style={{ color: C.muted, fontSize: 13, marginTop: 12 }}>Loading…</p>
  </div>
);

const SectionTitle = ({ icon, children }) => (
  <div style={styles.sectionTitle}>
    <span style={styles.sectionIcon}>{icon}</span>
    <span>{children}</span>
  </div>
);

const Card = ({ children, style }) => (
  <div style={{ ...styles.card, ...style }}>{children}</div>
);

// ── Priority badge ────────────────────────────────────────────────────────────
const PBadge = ({ p }) => {
  const cfg = {
    P1: { bg: C.p1bg, color: C.p1, border: C.p1border },
    P2: { bg: C.p2bg, color: C.p2, border: C.p2border },
    P3: { bg: C.p3bg, color: C.p3, border: C.p3border },
  }[p] || { bg: "#f7fafc", color: C.muted, border: C.border };
  return (
    <span style={{ ...styles.pbadge, background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}` }}>
      {p}
    </span>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
export default function Dashboard({ onBack }) {
  const [projects,    setProjects]    = useState([]);
  const [projectId,   setProjectId]   = useState(null);
  const [releases,    setReleases]    = useState([]);
  const [releaseId,   setReleaseId]   = useState(null);
  const [cmpReleaseId,setCmpRelId]    = useState(null);
  const [summary,     setSummary]     = useState(null);
  const [trend,       setTrend]       = useState(null);
  const [moduleRisk,  setModuleRisk]  = useState([]);
  const [topRisk,     setTopRisk]     = useState([]);
  const [comparison,  setComparison]  = useState(null);
  const [loading,     setLoading]     = useState({});
  const [activeTab,   setActiveTab]   = useState("overview");

  const set = (key, val) => setLoading((p) => ({ ...p, [key]: val }));

  // ── Load projects on mount ─────────────────────────────────────────────────
  useEffect(() => {
    api("/api/projects").then((data) => {
      setProjects(data);
      if (data.length) setProjectId(data[0].id);
    });
  }, []);

  // ── Load releases when project changes ────────────────────────────────────
  useEffect(() => {
    if (!projectId) return;
    setReleases([]); setReleaseId(null); setCmpRelId(null);
    setSummary(null); setTrend(null);

    set("releases", true);
    Promise.all([
      api(`/api/dashboard/releases?project_id=${projectId}`),
      api(`/api/dashboard/summary?project_id=${projectId}`),
      api(`/api/dashboard/execution-history?project_id=${projectId}`),
    ]).then(([rels, sum, tr]) => {
      setReleases(rels);
      setSummary(sum);
      setTrend(tr);
      if (rels.length) {
        const latest = rels[rels.length - 1];
        setReleaseId(latest.release_id);
        if (rels.length >= 2) setCmpRelId(rels[rels.length - 2].release_id);
      }
    }).finally(() => set("releases", false));
  }, [projectId]);

  // ── Load release-level data when releaseId changes ────────────────────────
  useEffect(() => {
    if (!releaseId) return;
    set("release", true);
    Promise.all([
      api(`/api/dashboard/module-risk?release_id=${releaseId}`),
      api(`/api/dashboard/top-risk?release_id=${releaseId}&limit=10`),
    ]).then(([mod, top]) => {
      setModuleRisk(mod);
      setTopRisk(top);
    }).finally(() => set("release", false));
  }, [releaseId]);

  // ── Load comparison when both releases selected ───────────────────────────
  useEffect(() => {
    if (!releaseId || !cmpReleaseId || releaseId === cmpReleaseId) {
      setComparison(null); return;
    }
    api(`/api/dashboard/compare?release1=${cmpReleaseId}&release2=${releaseId}`)
      .then(setComparison);
  }, [releaseId, cmpReleaseId]);

  // ── Derived chart data ─────────────────────────────────────────────────────
  const trendChart = trend ? {
    labels: trend.labels,
    datasets: [
      { label: "P1 Critical", data: trend.p1_trend, borderColor: C.p1, backgroundColor: "rgba(229,62,62,0.08)", tension: 0.4, fill: true, pointBackgroundColor: C.p1, pointRadius: 4 },
      { label: "P2 Moderate", data: trend.p2_trend, borderColor: C.p2, backgroundColor: "rgba(214,158,46,0.08)", tension: 0.4, fill: true, pointBackgroundColor: C.p2, pointRadius: 4 },
      { label: "P3 Low",      data: trend.p3_trend, borderColor: C.p3, backgroundColor: "rgba(56,161,105,0.08)", tension: 0.4, fill: true, pointBackgroundColor: C.p3, pointRadius: 4 },
    ],
  } : null;

  const moduleChart = moduleRisk.length ? {
    labels: moduleRisk.map((m) => m.module),
    datasets: [{
      label: "Avg Risk Score",
      data: moduleRisk.map((m) => m.avg_risk),
      backgroundColor: moduleRisk.map((m) =>
        m.avg_risk >= 7 ? "rgba(229,62,62,0.75)"
        : m.avg_risk >= 5 ? "rgba(214,158,46,0.75)"
        : "rgba(56,161,105,0.75)"
      ),
      borderRadius: 6,
      borderSkipped: false,
    }],
  } : null;

  const currentRelease = releases.find((r) => r.release_id === releaseId);
  const donutChart = currentRelease ? {
    labels: ["P1 Critical", "P2 Moderate", "P3 Low"],
    datasets: [{
      data: [currentRelease.p1, currentRelease.p2, currentRelease.p3],
      backgroundColor: [C.p1, C.p2, C.p3],
      borderWidth: 2,
      borderColor: "#fff",
      hoverOffset: 6,
    }],
  } : null;

  const chartOpts = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { position: "bottom", labels: { font: { size: 12 }, padding: 16, boxWidth: 12 } } },
    scales: { x: { grid: { display: false } }, y: { grid: { color: "#f0f0f0" }, beginAtZero: true } },
  };
  const barOpts = { ...chartOpts, indexAxis: "y", scales: { x: { grid: { color: "#f0f0f0" }, beginAtZero: true, max: 10 }, y: { grid: { display: false } } } };
  const donutOpts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { font: { size: 12 }, padding: 16, boxWidth: 12 } } } };

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div style={styles.page}>
      {/* ── Header ── */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <div style={styles.headerIcon}>📊</div>
          <div>
            <div style={styles.headerTitle}>QA Intelligence Dashboard</div>
            <div style={styles.headerSub}>Release analytics · Risk trends · Module insights</div>
          </div>
        </div>

        {/* Project + Release selectors */}
        <div style={styles.selectors}>
          <div style={styles.selectorGroup}>
            <label style={styles.selectorLabel}>PROJECT</label>
            <select style={styles.select} value={projectId || ""} onChange={(e) => setProjectId(Number(e.target.value))}>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <div style={styles.selectorGroup}>
            <label style={styles.selectorLabel}>RELEASE</label>
            <select style={styles.select} value={releaseId || ""} onChange={(e) => setReleaseId(Number(e.target.value))}>
              {releases.map((r) => (
                <option key={r.release_id} value={r.release_id}>{r.release_name} · {r.date}</option>
              ))}
            </select>
          </div>
          <div style={styles.selectorGroup}>
            <label style={styles.selectorLabel}>COMPARE WITH</label>
            <select style={styles.select} value={cmpReleaseId || ""} onChange={(e) => setCmpRelId(Number(e.target.value))}>
              <option value="">— none —</option>
              {releases.filter((r) => r.release_id !== releaseId).map((r) => (
                <option key={r.release_id} value={r.release_id}>{r.release_name} · {r.date}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* ── Tab bar ── */}
      <div style={styles.tabBar}>
        {onBack && (
          <button onClick={onBack} style={styles.backTabBtn}>
            ← Back to Analysis
          </button>
        )}
        <div style={styles.tabDivider} />
        {[
          { key: "overview",    label: "📋 Overview" },
          { key: "trends",      label: "📈 Trends" },
          { key: "modules",     label: "🧩 Module Risk" },
          { key: "toprisk",     label: "🔥 Top Risk" },
          { key: "comparison",  label: "⚖️ Comparison" },
          { key: "releases",    label: "📦 All Releases" },
        ].map((t) => (
          <button
            key={t.key}
            style={activeTab === t.key ? styles.tabActive : styles.tab}
            onClick={() => setActiveTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={styles.body}>
        {/* ══════════════ OVERVIEW TAB ══════════════ */}
        {activeTab === "overview" && (
          <div>
            {!summary ? <Spinner /> : (
              <>
                {/* Hero stats */}
                <div style={styles.statsGrid}>
                  {[
                    { label: "Total Test Cases", value: summary.latest_release?.total ?? "—",       color: C.accent,  icon: "🧪" },
                    { label: "P1 Critical",       value: summary.latest_release?.p1    ?? "—",       color: C.p1,      icon: "🔴" },
                    { label: "P2 Moderate",       value: summary.latest_release?.p2    ?? "—",       color: C.p2,      icon: "🟡" },
                    { label: "P3 Low Risk",        value: summary.latest_release?.p3    ?? "—",       color: C.p3,      icon: "🟢" },
                    { label: "Recommended",        value: summary.latest_release?.recommended ?? "—", color: C.ink,     icon: "✅" },
                    { label: "Avg Risk Score",     value: summary.latest_release?.avg_risk ?? "—",   color: "#805ad5", icon: "⚡" },
                  ].map((s) => (
                    <Card key={s.label} style={styles.statCard}>
                      <div style={styles.statIcon}>{s.icon}</div>
                      <div style={{ ...styles.statValue, color: s.color }}>{s.value}</div>
                      <div style={styles.statLabel}>{s.label}</div>
                    </Card>
                  ))}
                </div>

                {/* Mini project info */}
                <div style={styles.projectInfo}>
                  <span style={styles.projectInfoItem}>📁 <strong>{summary.project_name}</strong></span>
                  <span style={styles.projectInfoDivider}>·</span>
                  <span style={styles.projectInfoItem}>📦 {summary.total_releases} releases</span>
                  <span style={styles.projectInfoDivider}>·</span>
                  <span style={styles.projectInfoItem}>🧪 {summary.total_testcases} test cases</span>
                  {summary.latest_release && (
                    <>
                      <span style={styles.projectInfoDivider}>·</span>
                      <span style={styles.projectInfoItem}>🕐 Latest: <strong>{summary.latest_release.name}</strong> ({summary.latest_release.date})</span>
                    </>
                  )}
                </div>

                {/* Overview charts row */}
                <div style={styles.chartsRow}>
                  <Card style={{ flex: 1 }}>
                    <SectionTitle icon="🍩">Priority Distribution — {currentRelease?.release_name}</SectionTitle>
                    {donutChart
                      ? <div style={{ height: 260 }}><Doughnut data={donutChart} options={donutOpts} /></div>
                      : <div style={styles.empty}>No data for selected release</div>}
                  </Card>
                  <Card style={{ flex: 2 }}>
                    <SectionTitle icon="🧩">Module Risk Heatmap — {currentRelease?.release_name}</SectionTitle>
                    {moduleChart
                      ? <div style={{ height: 260 }}><Bar data={moduleChart} options={barOpts} /></div>
                      : <div style={styles.empty}>No module data</div>}
                  </Card>
                </div>
              </>
            )}
          </div>
        )}

        {/* ══════════════ TRENDS TAB ══════════════ */}
        {activeTab === "trends" && (
          <div>
            <Card>
              <SectionTitle icon="📈">P1 / P2 / P3 Trend Across Releases</SectionTitle>
              {trendChart
                ? <div style={{ height: 320 }}><Line data={trendChart} options={{ ...chartOpts, plugins: { ...chartOpts.plugins, legend: { position: "bottom" } } }} /></div>
                : <Spinner />}
            </Card>

            {trend && releases.length > 0 && (
              <Card style={{ marginTop: 20 }}>
                <SectionTitle icon="📊">Release Summary Table</SectionTitle>
                <div style={styles.tableWrap}>
                  <table style={styles.table}>
                    <thead>
                      <tr>
                        {["Release", "Date", "Total", "P1", "P2", "P3", "Avg Risk", "P1 %"].map((h) => (
                          <th key={h} style={styles.th}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {releases.map((r, i) => (
                        <tr key={r.release_id} style={i % 2 === 0 ? styles.trEven : {}}>
                          <td style={styles.td}><strong>{r.release_name}</strong></td>
                          <td style={styles.td}>{r.date}</td>
                          <td style={styles.td}>{r.total_tests}</td>
                          <td style={{ ...styles.td, color: C.p1, fontWeight: 700 }}>{r.p1}</td>
                          <td style={{ ...styles.td, color: C.p2, fontWeight: 700 }}>{r.p2}</td>
                          <td style={{ ...styles.td, color: C.p3, fontWeight: 700 }}>{r.p3}</td>
                          <td style={styles.td}>{r.avg_risk}</td>
                          <td style={styles.td}>{pct(r.p1, r.total_tests)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
          </div>
        )}

        {/* ══════════════ MODULE RISK TAB ══════════════ */}
        {activeTab === "modules" && (
          <div>
            <Card>
              <SectionTitle icon="🧩">Module Risk Analysis — {currentRelease?.release_name}</SectionTitle>
              {loading.release ? <Spinner /> : moduleChart
                ? <div style={{ height: Math.max(280, moduleRisk.length * 44) }}><Bar data={moduleChart} options={barOpts} /></div>
                : <div style={styles.empty}>No module data for this release</div>}
            </Card>

            {moduleRisk.length > 0 && (
              <Card style={{ marginTop: 20 }}>
                <SectionTitle icon="📋">Module Risk Table</SectionTitle>
                <div style={styles.tableWrap}>
                  <table style={styles.table}>
                    <thead>
                      <tr>
                        {["#", "Module", "Avg Risk", "Test Count", "P1 Cases", "Risk Level"].map((h) => (
                          <th key={h} style={styles.th}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {moduleRisk.map((m, i) => (
                        <tr key={m.module} style={i % 2 === 0 ? styles.trEven : {}}>
                          <td style={styles.td}>{i + 1}</td>
                          <td style={{ ...styles.td, fontWeight: 600 }}>{m.module}</td>
                          <td style={{ ...styles.td, fontWeight: 700, color: m.avg_risk >= 7 ? C.p1 : m.avg_risk >= 5 ? C.p2 : C.p3 }}>{m.avg_risk}</td>
                          <td style={styles.td}>{m.test_count}</td>
                          <td style={{ ...styles.td, color: C.p1 }}>{m.p1_count}</td>
                          <td style={styles.td}>
                            <span style={{
                              padding: "2px 10px", borderRadius: 4, fontSize: 11, fontWeight: 700,
                              background: m.avg_risk >= 7 ? C.p1bg : m.avg_risk >= 5 ? C.p2bg : C.p3bg,
                              color: m.avg_risk >= 7 ? C.p1 : m.avg_risk >= 5 ? C.p2 : C.p3,
                            }}>
                              {m.avg_risk >= 7 ? "HIGH RISK" : m.avg_risk >= 5 ? "MEDIUM" : "LOW RISK"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            )}
          </div>
        )}

        {/* ══════════════ TOP RISK TAB ══════════════ */}
        {activeTab === "toprisk" && (
          <Card>
            <SectionTitle icon="🔥">Top Risk Test Cases — {currentRelease?.release_name}</SectionTitle>
            {loading.release ? <Spinner /> : topRisk.length === 0
              ? <div style={styles.empty}>No data</div>
              : (
                <div style={styles.tableWrap}>
                  <table style={styles.table}>
                    <thead>
                      <tr>
                        {["#", "Test Case", "Module", "Severity", "Base Score", "Final Score", "Priority", "Recommended", "Adj Reason"].map((h) => (
                          <th key={h} style={styles.th}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {topRisk.map((t, i) => (
                        <tr key={i} style={i % 2 === 0 ? styles.trEven : {}}>
                          <td style={styles.td}>{i + 1}</td>
                          <td style={{ ...styles.td, fontWeight: 600, maxWidth: 220 }}>{t.title}</td>
                          <td style={styles.td}>{t.module}</td>
                          <td style={styles.td}>{t.severity}</td>
                          <td style={{ ...styles.td, color: C.muted }}>{t.risk_score ?? "—"}</td>
                          <td style={{ ...styles.td, fontWeight: 700, color: (t.final_score >= 8 ? C.p1 : t.final_score >= 5 ? C.p2 : C.p3) }}>
                            {t.final_score ?? "—"}
                          </td>
                          <td style={styles.td}><PBadge p={t.priority} /></td>
                          <td style={styles.td}>
                            <span style={{ color: t.recommended === "Yes" ? C.p3 : C.muted, fontWeight: 600 }}>
                              {t.recommended === "Yes" ? "✅ Yes" : "—"}
                            </span>
                          </td>
                          <td style={{ ...styles.td, fontSize: 11, color: C.muted, maxWidth: 180 }}>{t.adj_reason || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
          </Card>
        )}

        {/* ══════════════ COMPARISON TAB ══════════════ */}
        {activeTab === "comparison" && (
          <div>
            {!cmpReleaseId || releaseId === cmpReleaseId ? (
              <div style={styles.emptyState}>
                <div style={styles.emptyIcon}>⚖️</div>
                <p>Select a different release in the <strong>Compare With</strong> dropdown above to see a side-by-side comparison.</p>
              </div>
            ) : !comparison ? <Spinner /> : (
              <>
                {/* Risk trend banner */}
                <div style={{
                  ...styles.trendBanner,
                  background: comparison.risk_trend === "improved" ? C.p3bg : comparison.risk_trend === "worsened" ? C.p1bg : "#f7fafc",
                  borderColor: comparison.risk_trend === "improved" ? C.p3 : comparison.risk_trend === "worsened" ? C.p1 : C.border,
                  color: comparison.risk_trend === "improved" ? C.p3 : comparison.risk_trend === "worsened" ? C.p1 : C.ink,
                }}>
                  <span style={{ fontSize: 24 }}>
                    {comparison.risk_trend === "improved" ? "✅" : comparison.risk_trend === "worsened" ? "⚠️" : "➡️"}
                  </span>
                  <div>
                    <div style={{ fontWeight: 800, fontSize: 16 }}>
                      Risk {comparison.risk_trend === "improved" ? "IMPROVED" : comparison.risk_trend === "worsened" ? "WORSENED" : "STABLE"}
                    </div>
                    <div style={{ fontSize: 13, opacity: 0.8 }}>
                      Comparing <strong>{comparison.release1}</strong> → <strong>{comparison.release2}</strong>
                      {" · "}Avg risk change: <strong>{comparison.avg_risk_change > 0 ? "+" : ""}{comparison.avg_risk_change}</strong>
                    </div>
                  </div>
                </div>

                {/* Side-by-side stat cards */}
                <div style={styles.cmpGrid}>
                  {[
                    { label: "Total Tests", k: "total", icon: "🧪", deltaInvert: false },
                    { label: "P1 Critical", k: "p1",    icon: "🔴", deltaInvert: true  },
                    { label: "P2 Moderate", k: "p2",    icon: "🟡", deltaInvert: false },
                    { label: "P3 Low Risk", k: "p3",    icon: "🟢", deltaInvert: false },
                  ].map(({ label, k, icon, deltaInvert }) => {
                    const v1 = comparison.release1_stats[k];
                    const v2 = comparison.release2_stats[k];
                    const delta = { total: v2 - v1, p1: comparison.p1_change, p2: comparison.p2_change, p3: comparison.p3_change }[k];
                    return (
                      <Card key={k} style={styles.cmpCard}>
                        <div style={styles.cmpCardIcon}>{icon}</div>
                        <div style={styles.cmpCardLabel}>{label}</div>
                        <div style={styles.cmpRow}>
                          <div style={styles.cmpVal}>
                            <div style={styles.cmpRelName}>{comparison.release1}</div>
                            <div style={styles.cmpNum}>{v1}</div>
                          </div>
                          <div style={styles.cmpArrow}>→</div>
                          <div style={styles.cmpVal}>
                            <div style={styles.cmpRelName}>{comparison.release2}</div>
                            <div style={styles.cmpNum}>{v2}</div>
                          </div>
                        </div>
                        <div style={{ textAlign: "center", marginTop: 8 }}>
                          <DeltaBadge value={delta} invert={deltaInvert} />
                        </div>
                      </Card>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        )}

        {/* ══════════════ ALL RELEASES TAB ══════════════ */}
        {activeTab === "releases" && (
          <Card>
            <SectionTitle icon="📦">All Releases — {projects.find((p) => p.id === projectId)?.name}</SectionTitle>
            {loading.releases ? <Spinner /> : releases.length === 0
              ? <div style={styles.empty}>No releases found. Run an analysis first.</div>
              : (
                <div style={styles.tableWrap}>
                  <table style={styles.table}>
                    <thead>
                      <tr>
                        {["Release", "Date", "Total", "P1", "P2", "P3", "Avg Risk", "P1 %", "Actions"].map((h) => (
                          <th key={h} style={styles.th}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {[...releases].reverse().map((r, i) => (
                        <tr key={r.release_id} style={i % 2 === 0 ? styles.trEven : {}}>
                          <td style={{ ...styles.td, fontWeight: 700 }}>{r.release_name}</td>
                          <td style={styles.td}>{r.date}</td>
                          <td style={styles.td}>{r.total_tests}</td>
                          <td style={{ ...styles.td, color: C.p1, fontWeight: 700 }}>{r.p1}</td>
                          <td style={{ ...styles.td, color: C.p2, fontWeight: 700 }}>{r.p2}</td>
                          <td style={{ ...styles.td, color: C.p3, fontWeight: 700 }}>{r.p3}</td>
                          <td style={styles.td}>{r.avg_risk}</td>
                          <td style={styles.td}>{pct(r.p1, r.total_tests)}%</td>
                          <td style={styles.td}>
                            <button
                              style={styles.viewBtn}
                              onClick={() => { setReleaseId(r.release_id); setActiveTab("overview"); }}
                            >
                              View
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
          </Card>
        )}
      </div>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
const styles = {
  page:        { minHeight: "100vh", background: C.bg, fontFamily: "'Inter', sans-serif" },
  header:      { background: C.surface, borderBottom: `2px solid ${C.ink}`, padding: "0 2rem", display: "flex", alignItems: "center", justifyContent: "space-between", gap: "2rem", minHeight: 72, flexWrap: "wrap" },
  headerLeft:  { display: "flex", alignItems: "center", gap: 14 },
  headerIcon:  { fontSize: 28 },
  headerTitle: { fontFamily: "'Space Grotesk', sans-serif", fontWeight: 800, fontSize: "1.1rem", color: C.ink },
  headerSub:   { fontSize: "0.68rem", color: C.muted, marginTop: 2 },
  selectors:   { display: "flex", gap: 16, alignItems: "flex-end", flexWrap: "wrap" },
  selectorGroup: { display: "flex", flexDirection: "column", gap: 4 },
  selectorLabel: { fontSize: "0.62rem", fontWeight: 800, letterSpacing: "1px", color: C.muted },
  select:      { padding: "7px 12px", border: `1.5px solid ${C.border}`, borderRadius: 7, background: C.surface, fontSize: "0.84rem", fontFamily: "'Inter', sans-serif", cursor: "pointer", outline: "none", minWidth: 180 },
  tabBar:      { background: C.surface, borderBottom: `1px solid ${C.border}`, padding: "0 2rem", display: "flex", gap: 4, overflowX: "auto" },
  tab:         { padding: "12px 18px", border: "none", background: "transparent", cursor: "pointer", fontSize: "0.84rem", fontWeight: 500, color: C.muted, borderBottom: "2px solid transparent", transition: "all 0.15s", whiteSpace: "nowrap", fontFamily: "'Inter', sans-serif" },
  tabActive:   { padding: "12px 18px", border: "none", background: "transparent", cursor: "pointer", fontSize: "0.84rem", fontWeight: 700, color: C.ink, borderBottom: `2px solid ${C.ink}`, transition: "all 0.15s", whiteSpace: "nowrap", fontFamily: "'Inter', sans-serif" },
  body:        { padding: "1.8rem 2rem", maxWidth: 1400, margin: "0 auto" },
  card:        { background: C.surface, border: `1.5px solid ${C.border}`, borderRadius: 12, padding: "1.4rem 1.6rem", boxShadow: "0 1px 8px rgba(0,0,0,0.05)", marginBottom: 20 },
  statsGrid:   { display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 14, marginBottom: 20 },
  statCard:    { textAlign: "center", padding: "1.2rem 1rem", marginBottom: 0 },
  statIcon:    { fontSize: 22, marginBottom: 8 },
  statValue:   { fontSize: "1.9rem", fontWeight: 800, fontFamily: "'Space Grotesk', sans-serif", lineHeight: 1 },
  statLabel:   { fontSize: "0.7rem", color: C.muted, marginTop: 6, textTransform: "uppercase", letterSpacing: "0.6px", fontWeight: 600 },
  sectionTitle:{ display: "flex", alignItems: "center", gap: 10, fontWeight: 800, fontSize: "0.92rem", color: C.ink, marginBottom: "1.2rem", fontFamily: "'Space Grotesk', sans-serif" },
  sectionIcon: { fontSize: 16 },
  chartsRow:   { display: "flex", gap: 20 },
  tableWrap:   { overflowX: "auto" },
  table:       { width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" },
  th:          { padding: "10px 12px", background: C.ink, color: "#fff", fontWeight: 700, textAlign: "left", fontSize: "0.75rem", letterSpacing: "0.4px", whiteSpace: "nowrap" },
  td:          { padding: "9px 12px", borderBottom: `1px solid ${C.border}`, color: C.ink, verticalAlign: "top" },
  trEven:      { background: "#fafbfc" },
  pbadge:      { padding: "2px 10px", borderRadius: 5, fontSize: 11, fontWeight: 800 },
  empty:       { textAlign: "center", padding: "2rem", color: C.muted, fontSize: "0.9rem" },
  emptyState:  { textAlign: "center", padding: "4rem 2rem", color: C.muted },
  emptyIcon:   { fontSize: 48, marginBottom: 16 },
  projectInfo: { display: "flex", alignItems: "center", gap: 8, padding: "10px 16px", background: "#edf2f7", borderRadius: 8, marginBottom: 20, fontSize: "0.83rem", flexWrap: "wrap" },
  projectInfoItem: { color: C.ink },
  projectInfoDivider: { color: C.muted },
  spinnerWrap: { display: "flex", flexDirection: "column", alignItems: "center", padding: "3rem" },
  spinner:     { width: 32, height: 32, border: `3px solid ${C.border}`, borderTopColor: C.ink, borderRadius: "50%", animation: "spin 0.7s linear infinite" },
  trendBanner: { display: "flex", alignItems: "center", gap: 16, padding: "1.2rem 1.6rem", borderRadius: 10, border: "1.5px solid", marginBottom: 20 },
  cmpGrid:     { display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 },
  cmpCard:     { textAlign: "center", marginBottom: 0 },
  cmpCardIcon: { fontSize: 24, marginBottom: 8 },
  cmpCardLabel:{ fontSize: "0.75rem", fontWeight: 700, color: C.muted, textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 12 },
  cmpRow:      { display: "flex", alignItems: "center", justifyContent: "center", gap: 12 },
  cmpVal:      { textAlign: "center" },
  cmpRelName:  { fontSize: "0.68rem", color: C.muted, marginBottom: 4 },
  cmpNum:      { fontSize: "1.6rem", fontWeight: 800, fontFamily: "'Space Grotesk', sans-serif", color: C.ink },
  cmpArrow:    { fontSize: 18, color: C.muted },
  deltaGood:   { background: C.p3bg, color: C.p3, border: `1px solid ${C.p3border}`, padding: "2px 10px", borderRadius: 5, fontSize: 12, fontWeight: 700 },
  deltaBad:    { background: C.p1bg, color: C.p1, border: `1px solid ${C.p1border}`, padding: "2px 10px", borderRadius: 5, fontSize: 12, fontWeight: 700 },
  deltaNeutral:{ background: "#f7fafc", color: C.muted, border: `1px solid ${C.border}`, padding: "2px 10px", borderRadius: 5, fontSize: 12, fontWeight: 700 },
  viewBtn:     { padding: "4px 14px", background: C.ink, color: "#fff", border: "none", borderRadius: 5, fontSize: "0.78rem", fontWeight: 600, cursor: "pointer" },
  backTabBtn:  { padding: "10px 16px", background: C.ink, color: "#fff", border: "none", borderBottom: "2px solid transparent", fontSize: "0.84rem", fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap", fontFamily: "'Inter', sans-serif", flexShrink: 0 },
  tabDivider:  { width: 1, background: "#e2e8f0", margin: "8px 4px", flexShrink: 0 },
};