import { useState } from "react";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";

export default function RegressionOptimizer({ mode, openaiKey, keyValid, selectedModel }) {
  const [file, setFile] = useState(null);
  const [formData, setFormData] = useState({ recent_modification_days: "", total_execution_days: "", total_testers: "", cases_per_tester_per_day: "" });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = (e) => {
    e.preventDefault(); setDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped && dropped.name.endsWith(".xlsx")) setFile(dropped);
    else setError("Please upload a valid .xlsx file.");
  };

  const handleSubmit = async () => {
    if (!file) return setError("Please upload an Excel file.");
    if (!formData.total_execution_days || !formData.total_testers || !formData.cases_per_tester_per_day)
      return setError("Please fill all mandatory fields.");
    if (mode === "online" && !openaiKey) return setError("Please enter your OpenAI API key in the header.");
    if (mode === "online" && keyValid === false) return setError("Your OpenAI API key is invalid. Please validate it first.");

    setError(null); setLoading(true); setResult(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("total_execution_days", formData.total_execution_days);
    fd.append("total_testers", formData.total_testers);
    fd.append("cases_per_tester_per_day", formData.cases_per_tester_per_day);
    fd.append("mode", mode);
    if (mode === "online" && openaiKey) fd.append("openai_key", openaiKey);
    if (mode === "offline" && selectedModel) fd.append("ollama_model", selectedModel);
    if (formData.recent_modification_days) fd.append("recent_modification_days", formData.recent_modification_days);

    try {
      const res = await fetch(`${API_URL}/api/regression/analyze`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Analysis failed");
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const capacity = formData.total_execution_days * formData.total_testers * formData.cases_per_tester_per_day || 0;

  return (
    <div className="feature-page">
      <div className="feature-header">
        <div className="feature-badge">Feature 1</div>
        <h2 className="feature-title">Regression Optimizer</h2>
        <p className="feature-desc">
          Upload your test suite (up to 2,000 cases). AI assigns P1/P2/P3 priorities based on risk and execution capacity.
          {" "}<span className={`mode-badge ${mode === "online" ? "mode-badge-online" : "mode-badge-offline"}`}>
            {mode === "online" ? "🌐 OpenAI GPT — Enhanced Analysis" : "🔌 Offline — Local AI"}
          </span>
        </p>
      </div>

      <div className="content-grid">
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

      {error && <div className="error-msg">⚠ {error}</div>}

      <div className="action-row">
        <button className="btn-primary" onClick={handleSubmit} disabled={loading}>
          {loading ? <span className="loading-content"><span className="spinner" /> Analyzing with {mode === "online" ? "OpenAI..." : "Local AI..."}</span> : `⚡ Run ${mode === "online" ? "OpenAI" : "Offline"} Analysis`}
        </button>
      </div>

      {loading && (
        <div className="progress-card">
          <div className="progress-bar-track"><div className="progress-bar-fill animated" /></div>
          <p className="progress-text">{mode === "online" ? "🌐 OpenAI GPT is analyzing risk scores..." : "🔌 Local AI is calculating execution plan..."}</p>
        </div>
      )}

      {result && (
        <div className="results-section">
          <div className="results-header-row">
            <h3 className="results-title">📊 Analysis Complete</h3>
            <span className={`mode-badge ${result.mode === "online" ? "mode-badge-online" : "mode-badge-offline"}`}>
              {result.mode === "online" ? "🌐 OpenAI GPT" : "🔌 Offline AI"}
            </span>
          </div>
          <div className="stats-grid">
            <div className="stat-card total"><div className="stat-value">{result.total_cases}</div><div className="stat-label">Total Cases</div></div>
            <div className="stat-card p1"><div className="stat-value">{result.p1_count}</div><div className="stat-label">P1 Critical</div></div>
            <div className="stat-card p2"><div className="stat-value">{result.p2_count}</div><div className="stat-label">P2 Moderate</div></div>
            <div className="stat-card p3"><div className="stat-value">{result.p3_count}</div><div className="stat-label">P3 Low</div></div>
            <div className="stat-card recommended"><div className="stat-value">{result.recommended_count}</div><div className="stat-label">Recommended</div></div>
            <div className="stat-card coverage"><div className="stat-value">{result.coverage_percent}%</div><div className="stat-label">Coverage</div></div>
          </div>
          <div className="coverage-bar-section">
            <div className="coverage-label"><span>Execution Coverage</span><span>{result.coverage_percent}%</span></div>
            <div className="coverage-track"><div className="coverage-fill" style={{ width: `${result.coverage_percent}%` }} /></div>
          </div>
          <a href={`${API_URL}${result.download_url}`} className="btn-download" download>⬇ Download Regression Report (.xlsx)</a>
        </div>
      )}
    </div>
  );
}