import { useState, useRef } from "react";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";

export default function RegressionOptimizer({ mode, apiKey, keyType, keyValid, selectedModel }) {
  const [file, setFile] = useState(null);
  const [formData, setFormData] = useState({
    recent_modification_days: "",
    total_execution_days: "",
    total_testers: "",
    cases_per_tester_per_day: "",
    project_name: "",
    release_name: "",
    changed_modules: "",
    frozen_modules: "",
  });
  const [loading, setLoading] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const abortRef = useRef(null);

  const handleDrop = (e) => {
    e.preventDefault(); setDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped && dropped.name.endsWith(".xlsx")) setFile(dropped);
    else setError("Please upload a valid .xlsx file.");
  };

  const handleStop = () => {
    if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
    setStopped(true); setLoading(false);
    setError("⛔ Analysis stopped by user.");
  };

  const handleSubmit = async () => {
    if (!file) return setError("Please upload an Excel file.");
    if (!formData.total_execution_days || !formData.total_testers || !formData.cases_per_tester_per_day)
      return setError("Please fill all mandatory fields.");
    if ((mode === "online" || mode === "gemini") && (!apiKey || apiKey.trim() === ""))
      return setError("Please enter your API key in the header bar above.");
    if ((mode === "online" || mode === "gemini") && keyValid === false)
      return setError("Your API key is invalid. Please check it and try again.");

    setError(null); setLoading(true); setResult(null); setStopped(false);

    const controller = new AbortController();
    abortRef.current = controller;

    const fd = new FormData();
    fd.append("file", file);
    fd.append("total_execution_days", formData.total_execution_days);
    fd.append("total_testers", formData.total_testers);
    fd.append("cases_per_tester_per_day", formData.cases_per_tester_per_day);
    fd.append("mode", mode);
    if (mode === "online")  fd.append("openai_key", apiKey);
    if (mode === "gemini")  fd.append("gemini_key", apiKey);
    if (mode === "offline") fd.append("ollama_model", selectedModel);
    if (formData.recent_modification_days) fd.append("recent_modification_days", formData.recent_modification_days);
    if (formData.project_name.trim())   fd.append("project_name", formData.project_name.trim());
    if (formData.release_name.trim())   fd.append("release_name", formData.release_name.trim());
    if (formData.changed_modules.trim()) fd.append("changed_modules", formData.changed_modules.trim());
    if (formData.frozen_modules.trim())  fd.append("frozen_modules", formData.frozen_modules.trim());

    try {
      const res = await fetch(`${API_URL}/api/regression/analyze`, {
        method: "POST", body: fd, signal: controller.signal,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Analysis failed");
      setResult(data);
    } catch (err) {
      if (err.name !== "AbortError") setError(err.message);
    } finally { abortRef.current = null; setLoading(false); }
  };

  const capacity = formData.total_execution_days * formData.total_testers * formData.cases_per_tester_per_day || 0;
  const modeLabel = mode === "online" ? "OpenAI" : mode === "gemini" ? "Gemini" : "Offline";
  const modeIcon  = mode === "online" ? "🔵" : mode === "gemini" ? "🟢" : "🔌";

  return (
    <div className="feature-page">
      <div className="feature-header">
        <div className="feature-badge">Feature 1</div>
        <h2 className="feature-title">Regression Optimizer</h2>
        <p className="feature-desc">
          Upload your test suite (up to 2,000 cases). AI assigns P1/P2/P3 priorities based on risk,
          release context and execution history.{" "}
          <span className={`mode-badge ${mode === "online" ? "mode-badge-online" : mode === "gemini" ? "mode-badge-gemini" : "mode-badge-offline"}`}>
            {modeIcon} {modeLabel}
          </span>
        </p>
      </div>

      <div className="content-grid">
        {/* ── Upload ── */}
        <div className="card">
          <h3 className="card-title"><span className="step-badge">1</span> Upload Test Cases</h3>
          <div
            className={`dropzone ${dragOver ? "drag-over" : ""} ${file ? "has-file" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => document.getElementById("regression-file").click()}
          >
            <input id="regression-file" type="file" accept=".xlsx" style={{ display: "none" }} onChange={(e) => setFile(e.target.files[0])} />
            {file ? (
              <div className="file-info">
                <span className="file-icon">📊</span>
                <div><div className="file-name">{file.name}</div><div className="file-size">{(file.size / 1024).toFixed(1)} KB</div></div>
                <button className="remove-file" onClick={(e) => { e.stopPropagation(); setFile(null); }}>✕</button>
              </div>
            ) : (
              <div className="dropzone-empty">
                <div className="dropzone-icon">⬆️</div>
                <div className="dropzone-text">Drop Excel file here or click to browse</div>
                <div className="dropzone-hint">.xlsx · Max 2,000 test cases</div>
              </div>
            )}
          </div>
        </div>

        {/* ── Execution Planning ── */}
        <div className="card">
          <h3 className="card-title"><span className="step-badge">2</span> Execution Planning</h3>
          <div className="form-grid">
            <div className="form-group">
              <label className="form-label">Recent Modification Days <span className="optional">(optional)</span></label>
              <input type="number" className="form-input" placeholder="e.g. 30" value={formData.recent_modification_days} onChange={(e) => setFormData({ ...formData, recent_modification_days: e.target.value })} />
            </div>
            <div className="form-group">
              <label className="form-label">Execution Days <span className="required">*</span></label>
              <input type="number" className="form-input" placeholder="e.g. 5" min="1" value={formData.total_execution_days} onChange={(e) => setFormData({ ...formData, total_execution_days: e.target.value })} />
            </div>
            <div className="form-group">
              <label className="form-label">Total Testers <span className="required">*</span></label>
              <input type="number" className="form-input" placeholder="e.g. 3" min="1" value={formData.total_testers} onChange={(e) => setFormData({ ...formData, total_testers: e.target.value })} />
            </div>
            <div className="form-group">
              <label className="form-label">Cases / Tester / Day <span className="required">*</span></label>
              <input type="number" className="form-input" placeholder="e.g. 20" min="1" value={formData.cases_per_tester_per_day} onChange={(e) => setFormData({ ...formData, cases_per_tester_per_day: e.target.value })} />
            </div>
          </div>
          {capacity > 0 && <div className="capacity-pill">⚡ Execution Capacity: <strong>{capacity}</strong> test cases</div>}
        </div>
      </div>

      {/* ── Advanced: Project / Release / History ── */}
      <div className="card advanced-card">
        <button className="advanced-toggle" onClick={() => setShowAdvanced(!showAdvanced)}>
          <span>🧠 Release & History Settings</span>
          <span className="advanced-badge">Enables AI history scoring</span>
          <span className="advanced-chevron">{showAdvanced ? "▲" : "▼"}</span>
        </button>

        {showAdvanced && (
          <div className="advanced-body">
            <div className="advanced-info">
              <strong>How history scoring works:</strong> After AI assigns a base score, the system queries past releases to apply 3 extra rules:
              <span className="hist-rule hist-rule-red">+2 if failed in previous release</span>
              <span className="hist-rule hist-rule-amber">+2 if not run in last 3 releases</span>
              <span className="hist-rule hist-rule-blue">−3 if module is frozen</span>
              Scores are clamped 1–10. Requires Project Name + Release Name.
            </div>

            <div className="form-grid form-grid-4">
              <div className="form-group">
                <label className="form-label">Project Name <span className="optional">(optional)</span></label>
                <input
                  type="text" className="form-input"
                  placeholder="e.g. E-Commerce App"
                  value={formData.project_name}
                  onChange={(e) => setFormData({ ...formData, project_name: e.target.value })}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Release Name <span className="optional">(optional)</span></label>
                <input
                  type="text" className="form-input"
                  placeholder="e.g. v2.4.0 or Sprint-15"
                  value={formData.release_name}
                  onChange={(e) => setFormData({ ...formData, release_name: e.target.value })}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Changed Modules <span className="optional">(comma-separated)</span></label>
                <input
                  type="text" className="form-input"
                  placeholder="e.g. Cart,Orders,Checkout"
                  value={formData.changed_modules}
                  onChange={(e) => setFormData({ ...formData, changed_modules: e.target.value })}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Frozen Modules <span className="optional">(comma-separated)</span></label>
                <input
                  type="text" className="form-input"
                  placeholder="e.g. Auth,Payments"
                  value={formData.frozen_modules}
                  onChange={(e) => setFormData({ ...formData, frozen_modules: e.target.value })}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {error && <div className="error-msg">⚠ {error}</div>}

      <div className="action-row">
        {!loading ? (
          <button className="btn-primary" onClick={handleSubmit}>
            ⚡ Run {modeLabel} Analysis
          </button>
        ) : (
          <>
            <button className="btn-primary btn-disabled" disabled>
              <span className="loading-content"><span className="spinner" /> {modeIcon} Analyzing with {modeLabel}...</span>
            </button>
            <button className="btn-stop" onClick={handleStop}>⏹ Stop</button>
          </>
        )}
      </div>

      {loading && (
        <div className="progress-card">
          <div className="progress-bar-track"><div className="progress-bar-fill animated" /></div>
          <div className="progress-footer">
            <p className="progress-text">{modeIcon} {modeLabel} is analyzing risk scores — this may take a moment...</p>
            <button className="btn-stop-inline" onClick={handleStop}>⏹ Stop Analysis</button>
          </div>
        </div>
      )}

      {result && (
        <div className="results-section">
          <div className="results-header-row">
            <h3 className="results-title">📊 Analysis Complete</h3>
            <span className={`mode-badge ${result.mode === "online" ? "mode-badge-online" : result.mode === "gemini" ? "mode-badge-gemini" : "mode-badge-offline"}`}>
              {result.mode === "online" ? "🔵 OpenAI GPT" : result.mode === "gemini" ? "🟢 Google Gemini" : "🔌 Offline AI"}
            </span>
            {result.history_adjusted && (
              <span className="history-badge">🧠 History Adjusted</span>
            )}
            {result.release_aware && (
              <span className="release-badge">📦 Release Aware</span>
            )}
          </div>

          {/* ── Stats grid ── */}
          <div className="stats-grid">
            <div className="stat-card total"><div className="stat-value">{result.total_cases}</div><div className="stat-label">Total Cases</div></div>
            <div className="stat-card p1"><div className="stat-value">{result.p1_count}</div><div className="stat-label">P1 Critical</div></div>
            <div className="stat-card p2"><div className="stat-value">{result.p2_count}</div><div className="stat-label">P2 Moderate</div></div>
            <div className="stat-card p3"><div className="stat-value">{result.p3_count}</div><div className="stat-label">P3 Low</div></div>
            <div className="stat-card recommended"><div className="stat-value">{result.recommended_count}</div><div className="stat-label">Recommended</div></div>
            <div className="stat-card coverage"><div className="stat-value">{result.coverage_percent}%</div><div className="stat-label">Coverage</div></div>
          </div>

          {/* ── Coverage bar ── */}
          <div className="coverage-bar-section">
            <div className="coverage-label"><span>Execution Coverage</span><span>{result.coverage_percent}%</span></div>
            <div className="coverage-track"><div className="coverage-fill" style={{ width: `${result.coverage_percent}%` }} /></div>
          </div>

          {/* ── History adjustment summary pills ── */}
          {result.history_adjusted && (
            <div className="history-summary">
              <div className="history-summary-title">🧠 History-Based Adjustments Applied</div>
              <div className="history-pills">
                <div className="history-pill pill-red">
                  <span className="pill-icon">🔴</span>
                  <span className="pill-label">Previous Failure</span>
                  <span className="pill-rule">+2 score</span>
                </div>
                <div className="history-pill pill-amber">
                  <span className="pill-icon">🟠</span>
                  <span className="pill-label">Not Run × 3 Releases</span>
                  <span className="pill-rule">+2 score</span>
                </div>
                <div className="history-pill pill-blue">
                  <span className="pill-icon">🔵</span>
                  <span className="pill-label">Frozen Module</span>
                  <span className="pill-rule">−3 score</span>
                </div>
              </div>
              <p className="history-note">
                Both <strong>Base Risk Score</strong> and <strong>Adjusted Risk Score</strong> are shown in the Excel report.
                History rules are applied after the AI base score.
              </p>
            </div>
          )}

          {/* ── Release context panel ── */}
          {result.release_context && (
            <div className="release-summary">
              <div className="release-summary-title">📦 Release Context</div>
              <div className="release-pills">
                {result.release_context.current_release && (
                  <span className="rel-pill">Release #{result.release_context.current_release}</span>
                )}
                {result.release_context.changed_modules?.length > 0 && (
                  <span className="rel-pill rel-pill-green">🟢 Changed: {result.release_context.changed_modules.join(", ")}</span>
                )}
                {result.release_context.frozen_modules?.length > 0 && (
                  <span className="rel-pill rel-pill-blue">🔵 Frozen: {result.release_context.frozen_modules.join(", ")}</span>
                )}
                <span className="rel-pill rel-pill-green">↑ Boosted: {result.release_context.boosted_count}</span>
                <span className="rel-pill rel-pill-blue">↓ Reduced: {result.release_context.reduced_count}</span>
              </div>
            </div>
          )}

          {/* ── DB save confirmation ── */}
          {result.db_saved_count > 0 && (
            <div className="db-save-pill">
              ✅ <strong>{result.db_saved_count}</strong> test executions saved to database
              {formData.project_name && <> · Project: <strong>{formData.project_name}</strong></>}
              {formData.release_name && <> · Release: <strong>{formData.release_name}</strong></>}
            </div>
          )}

          <a href={`${API_URL}${result.download_url}`} className="btn-download" download>
            ⬇ Download Regression Report (.xlsx)
          </a>
        </div>
      )}
    </div>
  );
}