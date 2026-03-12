import { useState, useRef } from "react";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";

export default function AutomationAnalyzer({ mode, apiKey, keyType, keyValid, selectedModel }) {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const abortRef = useRef(null);

  const handleDrop = (e) => {
    e.preventDefault(); setDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped && dropped.name.endsWith(".xlsx")) setFile(dropped);
    else setError("Please upload a valid .xlsx file.");
  };

  const handleStop = () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setStopped(true);
    setLoading(false);
    setError("⛔ Analysis stopped by user.");
  };

  const handleSubmit = async () => {
    if (!file) return setError("Please upload an Excel file.");
    if ((mode === "online" || mode === "gemini") && (!apiKey || apiKey.trim() === ""))
      return setError("Please enter your API key in the header bar above.");
    if ((mode === "online" || mode === "gemini") && keyValid === false)
      return setError("Your API key is invalid. Please check it and try again.");

    setError(null); setLoading(true); setResult(null); setStopped(false);

    // Create AbortController for this request
    const controller = new AbortController();
    abortRef.current = controller;

    const fd = new FormData();
    fd.append("file", file);
    fd.append("mode", mode);
    if (mode === "online")  fd.append("openai_key", apiKey);
    if (mode === "gemini")  fd.append("gemini_key", apiKey);
    if (mode === "offline") fd.append("ollama_model", selectedModel);

    try {
      const res = await fetch(`${API_URL}/api/automation/analyze`, {
        method: "POST",
        body: fd,
        signal: controller.signal,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Analysis failed");
      setResult(data);
    } catch (err) {
      if (err.name === "AbortError") {
        // Already handled by handleStop
      } else {
        setError(err.message);
      }
    } finally {
      abortRef.current = null;
      setLoading(false);
    }
  };

  const getPct = (count, total) => (total ? Math.round((count / total) * 100) : 0);
  const modeLabel = mode === "online" ? "OpenAI GPT" : mode === "gemini" ? "Google Gemini" : "Offline AI";
  const modeIcon  = mode === "online" ? "🔵" : mode === "gemini" ? "🟢" : "🔌";

  return (
    <div className="feature-page">
      <div className="feature-header">
        <div className="feature-badge feature-badge-2">Feature 2</div>
        <h2 className="feature-title">Manual to Automation Analyzer</h2>
        <p className="feature-desc">
          Upload manual test cases. AI identifies automation candidates based on stability, repeatability and complexity.
          {" "}<span className={`mode-badge ${mode === "online" ? "mode-badge-online" : mode === "gemini" ? "mode-badge-gemini" : "mode-badge-offline"}`}>
            {modeIcon} {modeLabel}
          </span>
        </p>
      </div>

      <div className="content-grid">
        <div className="card">
          <h3 className="card-title"><span className="step-badge step-badge-green">1</span> Upload Test Cases</h3>
          <div
            className={`dropzone dropzone-green ${dragOver ? "drag-over" : ""} ${file ? "has-file" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => document.getElementById("automation-file").click()}
          >
            <input id="automation-file" type="file" accept=".xlsx" style={{ display: "none" }} onChange={(e) => setFile(e.target.files[0])} />
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
                <div className="dropzone-hint">.xlsx · Manual test cases</div>
              </div>
            )}
          </div>
        </div>

        <div className="card">
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
                <span className="criteria-icon">{c.icon}</span><span>{c.label}</span>
              </div>
            ))}
          </div>
          {(mode === "online" || mode === "gemini") && (
            <div className="online-advantage">
              <strong>{modeIcon} {modeLabel} Advantage:</strong> Provides deeper context analysis, better step interpretation, and more accurate confidence scoring than local models.
            </div>
          )}
        </div>
      </div>

      {error && <div className="error-msg">⚠ {error}</div>}

      <div className="action-row">
        {!loading ? (
          <button className="btn-primary btn-green" onClick={handleSubmit}>
            🤖 Analyze with {modeLabel}
          </button>
        ) : (
          <>
            <button className="btn-primary btn-green btn-disabled" disabled>
              <span className="loading-content"><span className="spinner" /> {modeIcon} Analyzing with {modeLabel}...</span>
            </button>
            <button className="btn-stop" onClick={handleStop}>
              ⏹ Stop
            </button>
          </>
        )}
      </div>

      {loading && (
        <div className="progress-card">
          <div className="progress-bar-track"><div className="progress-bar-fill animated green" /></div>
          <div className="progress-footer">
            <p className="progress-text">
              {modeIcon} {modeLabel} is evaluating automation suitability — this may take a moment...
            </p>
            <button className="btn-stop-inline" onClick={handleStop}>⏹ Stop Analysis</button>
          </div>
        </div>
      )}

      {result && (
        <div className="results-section">
          <div className="results-header-row">
            <h3 className="results-title">🤖 Automation Analysis Complete</h3>
            <span className={`mode-badge ${result.mode === "online" ? "mode-badge-online" : result.mode === "gemini" ? "mode-badge-gemini" : "mode-badge-offline"}`}>
              {result.mode === "online" ? "🔵 OpenAI GPT" : result.mode === "gemini" ? "🟢 Google Gemini" : "🔌 Offline AI"}
            </span>
          </div>
          <div className="stats-grid">
            <div className="stat-card total"><div className="stat-value">{result.total_cases}</div><div className="stat-label">Total Analyzed</div></div>
            <div className="stat-card p3"><div className="stat-value">{result.automatable_count}</div><div className="stat-label">Automatable</div></div>
            <div className="stat-card p2"><div className="stat-value">{result.partial_count}</div><div className="stat-label">Partial</div></div>
            <div className="stat-card p1"><div className="stat-value">{result.not_suitable_count}</div><div className="stat-label">Not Suitable</div></div>
          </div>
          <div className="suitability-bars">
            {[
              { label: "Automatable", count: result.automatable_count, color: "#1a7a4a", pct: getPct(result.automatable_count, result.total_cases) },
              { label: "Partial", count: result.partial_count, color: "#9a6400", pct: getPct(result.partial_count, result.total_cases) },
              { label: "Not Suitable", count: result.not_suitable_count, color: "#c0392b", pct: getPct(result.not_suitable_count, result.total_cases) },
            ].map((item) => (
              <div key={item.label} className="suit-bar-row">
                <div className="suit-bar-label"><span style={{ color: item.color }}>●</span> {item.label}</div>
                <div className="suit-bar-track"><div className="suit-bar-fill" style={{ width: `${item.pct}%`, background: item.color }} /></div>
                <div className="suit-bar-pct">{item.pct}%</div>
                <div className="suit-bar-count">({item.count})</div>
              </div>
            ))}
          </div>
          <a href={`${API_URL}${result.download_url}`} className="btn-download btn-download-green" download>⬇ Download Automation Report (.xlsx)</a>
        </div>
      )}
    </div>
  );
}