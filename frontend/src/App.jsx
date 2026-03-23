import { useState, useEffect } from "react";
import RegressionOptimizer from "./components/RegressionOptimizer";
import AutomationAnalyzer  from "./components/AutomationAnalyzer";
import Dashboard           from "./components/Dashboard";
import "./index.css";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";

export default function App() {
  const [activeTab, setActiveTab] = useState("regression");
  const [mode,      setMode]      = useState("offline");

  const [apiKey,      setApiKey]      = useState("");
  const [keyType,     setKeyType]     = useState(null);
  const [keyValid,    setKeyValid]    = useState(null);
  const [keyMessage,  setKeyMessage]  = useState("");
  const [validating,  setValidating]  = useState(false);
  const [showKey,     setShowKey]     = useState(false);

  const [selectedModel,   setSelectedModel]   = useState("phi3");
  const [suggestedModel,  setSuggestedModel]  = useState(null);
  const [availableModels, setAvailableModels] = useState([]);
  const [hardwareInfo,    setHardwareInfo]    = useState(null);
  const [showModelPanel,  setShowModelPanel]  = useState(false);
  const [pullingModel,    setPullingModel]    = useState(null);
  const [pullStatus,      setPullStatus]      = useState(null);

  useEffect(() => { fetchHardwareInfo(); }, []);

  const fetchHardwareInfo = async () => {
    try {
      const res  = await fetch(`${API_URL}/api/hardware`);
      const data = await res.json();
      setHardwareInfo(data.hardware);
      setAvailableModels(data.models || []);
      setSuggestedModel(data.suggested_model);
      const installed = data.installed_models || [];
      if (installed.includes(data.suggested_model)) setSelectedModel(data.suggested_model);
      else if (installed.length > 0) setSelectedModel(installed[0]);
    } catch (e) { console.log("Hardware info not available"); }
  };

  const detectKeyType = (key) => {
    if (!key) return null;
    if (key.startsWith("sk-"))  return "openai";
    if (key.startsWith("AIza")) return "gemini";
    return "unknown";
  };

  const handleKeyChange = (val) => {
    setApiKey(val); setKeyValid(null); setKeyMessage("");
    const detected = detectKeyType(val);
    setKeyType(detected);
    if (detected === "openai") setMode("online");
    if (detected === "gemini") setMode("gemini");
  };

  const validateKey = async () => {
    if (!apiKey) return;
    setValidating(true); setKeyValid(null); setKeyMessage("");
    try {
      const res  = await fetch(`${API_URL}/api/validate-key`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey }),
      });
      const data = await res.json();
      setKeyValid(data.valid); setKeyType(data.key_type); setKeyMessage(data.message);
      if (data.valid && data.key_type === "openai") setMode("online");
      if (data.valid && data.key_type === "gemini") setMode("gemini");
    } catch { setKeyValid(false); setKeyMessage("Could not reach backend."); }
    finally { setValidating(false); }
  };

  const pullModel = async (modelName) => {
    setPullingModel(modelName); setPullStatus(null);
    try {
      const res  = await fetch(`${API_URL}/api/pull-model`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: modelName }),
      });
      const data = await res.json();
      if (res.ok) { setPullStatus({ success: true,  message: `${modelName} downloaded!` }); setSelectedModel(modelName); fetchHardwareInfo(); }
      else        { setPullStatus({ success: false, message: data.detail }); }
    } catch { setPullStatus({ success: false, message: "Download failed." }); }
    finally { setPullingModel(null); }
  };

  const getModelInfo    = (name) => availableModels.find((m) => m.name === name) || null;
  const currentModel    = getModelInfo(selectedModel);
  const keyTypeLabel    = keyType === "openai" ? "🔵 OpenAI" : keyType === "gemini" ? "🟢 Gemini" : keyType === "unknown" ? "❓ Unknown" : null;
  const keyTypeBadgeCls = keyType === "openai" ? "badge-openai" : keyType === "gemini" ? "badge-gemini" : "badge-unknown";
  const modeLabel       = mode === "online" ? "🔵 OpenAI GPT" : mode === "gemini" ? "🟢 Google Gemini" : `🔌 Ollama · ${selectedModel}`;

  const isDashboard = activeTab === "dashboard";

  return (
    <div className="app">
      {/* ── Header (hidden on dashboard — dashboard has its own header) ── */}
      {!isDashboard && (
        <header className="header">
          <div className="header-inner">
            <div className="brand">
              <div className="brand-icon">
                <svg viewBox="0 0 40 40" fill="none">
                  <circle cx="20" cy="20" r="18" stroke="#fff" strokeWidth="2" />
                  <path d="M12 20 L18 26 L28 14" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <div>
                <h1 className="brand-title">AI QA Intelligence</h1>
                <p className="brand-subtitle">Decision Platform · {modeLabel}</p>
              </div>
            </div>

            <nav className="nav">
              <button className={`nav-btn ${activeTab === "regression" ? "active" : ""}`} onClick={() => setActiveTab("regression")}>
                <span className="nav-icon">⚡</span> Regression
              </button>
              <button className={`nav-btn ${activeTab === "automation" ? "active" : ""}`} onClick={() => setActiveTab("automation")}>
                <span className="nav-icon">🤖</span> Automation
              </button>
              <button className={`nav-btn nav-btn-dashboard`} onClick={() => setActiveTab("dashboard")}>
                <span className="nav-icon">📊</span> Dashboard
              </button>
            </nav>

            <div className="header-controls">
              <div className="mode-toggle-wrap">
                <button className={`mode-btn ${mode === "offline" ? "mode-active" : ""}`}        onClick={() => setMode("offline")}>🔌 Offline</button>
                <button className={`mode-btn ${mode === "online"  ? "mode-active-online" : ""}`}  onClick={() => setMode("online")}>🔵 OpenAI</button>
                <button className={`mode-btn ${mode === "gemini"  ? "mode-active-gemini" : ""}`}  onClick={() => setMode("gemini")}>🟢 Gemini</button>
              </div>

              {mode === "offline" && (
                <div className="model-selector-wrap">
                  <button className="model-selector-btn" onClick={() => setShowModelPanel(!showModelPanel)}>
                    🤖 <strong>{currentModel?.label || selectedModel}</strong>
                    <span className="model-size">{currentModel?.size}</span>
                    <span className="model-chevron">{showModelPanel ? "▲" : "▼"}</span>
                  </button>
                  {showModelPanel && (
                    <div className="model-panel">
                      <div className="model-panel-title">
                        Select Ollama Model
                        {hardwareInfo && <span className="hw-badge">💻 {hardwareInfo.ram_gb}GB RAM · {hardwareInfo.cpu_cores} cores</span>}
                      </div>
                      {availableModels.map((model) => (
                        <div key={model.name} className={`model-card ${selectedModel === model.name ? "model-card-active" : ""} ${!model.is_installed ? "model-card-dim" : ""}`}>
                          <div className="model-card-top">
                            <div className="model-card-info">
                              <div className="model-card-name">
                                {model.label}
                                {model.is_suggested && <span className="suggested-tag">⭐ Suggested</span>}
                                {!model.is_installed && <span className="not-installed-tag">Not installed</span>}
                              </div>
                              <div className="model-card-meta">📦 {model.size} · ⚡ {model.speed} · ✨ {model.quality}</div>
                              <div className="model-card-bestfor">🖥 {model.best_for}</div>
                            </div>
                            <div className="model-card-actions">
                              {model.is_installed
                                ? <button className={`model-select-btn ${selectedModel === model.name ? "selected" : ""}`} onClick={() => { setSelectedModel(model.name); setShowModelPanel(false); }}>{selectedModel === model.name ? "✓ Selected" : "Select"}</button>
                                : <button className="model-pull-btn" onClick={() => pullModel(model.name)} disabled={pullingModel === model.name}>{pullingModel === model.name ? "⬇ Downloading..." : "⬇ Download"}</button>
                              }
                            </div>
                          </div>
                        </div>
                      ))}
                      {pullStatus && <div className={`pull-status ${pullStatus.success ? "pull-success" : "pull-error"}`}>{pullStatus.success ? "✓" : "✗"} {pullStatus.message}</div>}
                      <div className="model-panel-note">💡 Download once — stays on your PC forever.</div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {(mode === "online" || mode === "gemini") && (
            <div className="api-key-bar">
              <div className="api-key-inner">
                <span className="api-key-label">🔑 API Key</span>
                <div className="api-key-input-wrap">
                  <input
                    type={showKey ? "text" : "password"}
                    className={`api-key-input ${!apiKey ? "input-missing" : keyValid === true ? "input-valid" : keyValid === false ? "input-invalid" : ""}`}
                    placeholder={mode === "gemini" ? "AIza... (Gemini key)" : "sk-... (OpenAI key)"}
                    value={apiKey} onChange={(e) => handleKeyChange(e.target.value)} autoFocus
                  />
                  <button className="key-toggle-btn" onClick={() => setShowKey(!showKey)}>{showKey ? "🙈" : "👁️"}</button>
                </div>
                {keyType && <span className={`key-type-badge ${keyTypeBadgeCls}`}>{keyTypeLabel}</span>}
                <button className="validate-btn" onClick={validateKey} disabled={validating || !apiKey}>{validating ? "Checking..." : "Validate"}</button>
                {!apiKey && <span className="key-status missing">← Enter your key here first</span>}
                {keyValid === true  && <span className="key-status valid">✓ {keyMessage}</span>}
                {keyValid === false && <span className="key-status invalid">✗ {keyMessage}</span>}
                <span className="api-key-note">OpenAI keys start with <code>sk-</code> · Gemini keys start with <code>AIza</code></span>
              </div>
            </div>
          )}
        </header>
      )}

      {/* Dashboard tab has its own full-page layout with its own header */}


      <main className={isDashboard ? "" : "main"}>
        {activeTab === "regression" && (
          <RegressionOptimizer mode={mode} apiKey={apiKey} keyType={keyType} keyValid={keyValid} selectedModel={selectedModel} />
        )}
        {activeTab === "automation" && (
          <AutomationAnalyzer mode={mode} apiKey={apiKey} keyType={keyType} keyValid={keyValid} selectedModel={selectedModel} />
        )}
        {activeTab === "dashboard" && <Dashboard onBack={() => setActiveTab("regression")} />}
      </main>

      {!isDashboard && (
        <footer className="footer">
          <p>AI QA Decision Intelligence Platform v2.0 · {modeLabel}</p>
        </footer>
      )}
    </div>
  );
}