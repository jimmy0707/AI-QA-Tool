import { useState } from "react";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";

export default function AutomationAnalyzer() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped && dropped.name.endsWith(".xlsx")) setFile(dropped);
    else setError("Please upload a valid .xlsx file.");
  };

  const handleSubmit = async () => {
    if (!file) return setError("Please upload an Excel file.");
    setError(null);
    setLoading(true);
    setResult(null);

    const fd = new FormData();
    fd.append("file", file);

    try {
      const res = await fetch(`${API_URL}/api/automation/analyze`, {
        method: "POST",
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Analysis failed");
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const getDonutPct = (count, total) => (total ? Math.round((count / total) * 100) : 0);

  return (
    <div className="feature-page">
      <div className="feature-header">
        <div className="feature-badge feature-badge-2">Feature 2</div>
        <h2 className="feature-title">Manual to Automation Analyzer</h2>
        <p className="feature-desc">
          Upload manual test cases and let AI identify which are candidates for automation —
          evaluating stability, repeatability, UI complexity, and integration dependencies.
        </p>
      </div>

      <div className="content-grid single-col">
        <div className="card">
          <h3 className="card-title">
            <span className="step-badge">1</span> Upload Manual Test Cases
          </h3>
          <div
            className={`dropzone ${dragOver ? "drag-over" : ""} ${file ? "has-file" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => document.getElementById("automation-file").click()}
          >
            <input
              id="automation-file"
              type="file"
              accept=".xlsx"
              style={{ display: "none" }}
              onChange={(e) => setFile(e.target.files[0])}
            />
            {file ? (
              <div className="file-info">
                <span className="file-icon">📊</span>
                <div>
                  <div className="file-name">{file.name}</div>
                  <div className="file-size">{(file.size / 1024).toFixed(1)} KB</div>
                </div>
                <button className="remove-file" onClick={(e) => { e.stopPropagation(); setFile(null); }}>✕</button>
              </div>
            ) : (
              <div className="dropzone-empty">
                <div className="dropzone-icon">⬆️</div>
                <div className="dropzone-text">Drop Excel file here or click to browse</div>
                <div className="dropzone-hint">.xlsx · Manual test cases</div>
              </div>
            )}
          </div>
        </div>

        <div className="card criteria-card">
          <h3 className="card-title">🔍 AI Evaluation Criteria</h3>
          <div className="criteria-grid">
            {[
              { icon: "🔄", label: "Repetitive & stable workflows" },
              { icon: "⚙️", label: "Backend validation suitability" },
              { icon: "🖥️", label: "UI dependency complexity" },
              { icon: "🔗", label: "External integration dependency" },
              { icon: "🔐", label: "OTP / Captcha handling" },
              { icon: "📊", label: "Dynamic data requirements" },
            ].map((c) => (
              <div key={c.label} className="criteria-item">
                <span className="criteria-icon">{c.icon}</span>
                <span>{c.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {error && <div className="error-msg">⚠ {error}</div>}

      <div className="action-row">
        <button className="btn-primary btn-green" onClick={handleSubmit} disabled={loading}>
          {loading ? (
            <span className="loading-content">
              <span className="spinner" /> Analyzing test cases...
            </span>
          ) : (
            "🤖 Analyze Automation Potential"
          )}
        </button>
      </div>

      {loading && (
        <div className="progress-card">
          <div className="progress-bar-track">
            <div className="progress-bar-fill animated green" />
          </div>
          <p className="progress-text">AI is evaluating automation suitability for each test case...</p>
        </div>
      )}

      {result && (
        <div className="results-section">
          <h3 className="results-title">🤖 Automation Analysis Complete</h3>
          <div className="stats-grid">
            <div className="stat-card total">
              <div className="stat-value">{result.total_cases}</div>
              <div className="stat-label">Total Analyzed</div>
            </div>
            <div className="stat-card p3">
              <div className="stat-value">{result.automatable_count}</div>
              <div className="stat-label">Automatable</div>
            </div>
            <div className="stat-card p2">
              <div className="stat-value">{result.partial_count}</div>
              <div className="stat-label">Partial</div>
            </div>
            <div className="stat-card p1">
              <div className="stat-value">{result.not_suitable_count}</div>
              <div className="stat-label">Not Suitable</div>
            </div>
          </div>

          <div className="suitability-bars">
            {[
              { label: "Automatable", count: result.automatable_count, color: "#22c55e", pct: getDonutPct(result.automatable_count, result.total_cases) },
              { label: "Partial", count: result.partial_count, color: "#f59e0b", pct: getDonutPct(result.partial_count, result.total_cases) },
              { label: "Not Suitable", count: result.not_suitable_count, color: "#ef4444", pct: getDonutPct(result.not_suitable_count, result.total_cases) },
            ].map((item) => (
              <div key={item.label} className="suit-bar-row">
                <div className="suit-bar-label">
                  <span style={{ color: item.color }}>●</span> {item.label}
                </div>
                <div className="suit-bar-track">
                  <div
                    className="suit-bar-fill"
                    style={{ width: `${item.pct}%`, background: item.color }}
                  />
                </div>
                <div className="suit-bar-pct">{item.pct}%</div>
                <div className="suit-bar-count">({item.count})</div>
              </div>
            ))}
          </div>

          <a href={`${API_URL}${result.download_url}`} className="btn-download btn-download-green" download>
            ⬇ Download Automation Report (.xlsx)
          </a>
        </div>
      )}
    </div>
  );
}
