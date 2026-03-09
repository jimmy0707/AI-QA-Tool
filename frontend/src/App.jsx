import { useState, useEffect } from "react";
import RegressionOptimizer from "./components/RegressionOptimizer";
import AutomationAnalyzer from "./components/AutomationAnalyzer";
import "./index.css";

const API_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";

// Auto-detect key type from format — no user selection needed
function detectKeyType(key) {
  if (!key) return null;
  if (key.startsWith("sk-")) return "openai";
  if (key.startsWith("AIza")) return "gemini";
  return "unknown";
}

const KEY_INFO = {
  openai: { label: "OpenAI GPT-4o-mini", icon: "🟢", color: "#0f6b35", bg: "#d1fae5", border: "#a7f3d0", mode: "online" },
  gemini:  { label: "Google Gemini 1.5 Flash", icon: "🔵", color: "#1a56db", bg: "#e8f0fe", border: "#93c5fd", mode: "gemini" },
  unknown: { label: "Unknown Key", icon: "❓", color: "#b45309", bg: "#fef3c7", border: "#fde68a", mode: null },
};

export default function App() {
  const [activeTab, setActiveTab]     = useState("regression");
  const [mode, setMode]               = useState("offline");
  const [apiKey, setApiKey]           = useState("");
  const [detectedType, setDetectedType] = useState(null);
  const [keyValid, setKeyValid]       = useState(null);   // null | true | false
  const [validating, setValidating]   = useState(false);
  const [showKey, setShowKey]         = useState(false);
  const [selectedModel, setSelectedModel] = useState("phi3");
  const [availableModels, setAvailableModels] = useState([]);
  const [hardwareInfo, setHardwareInfo]   = useState(null);
  const [suggestedModel, setSuggestedModel] = useState(null);
  const [showModelPanel, setShowModelPanel] = useState(false);
  const [pullingModel, setPullingModel]   = useState(null);
  const [pullStatus, setPullStatus]       = useState(null);

  useEffect(() => { fetchHardwareInfo(); }, []);

  const fetchHardwareInfo = async () => {
    try {
      const res = await fetch(`${API_URL}/api/hardware`);
      if (!res.ok) return;
      const data = await res.json();
      setHardwareInfo(data.hardware);
      setAvailableModels(data.models || []);
      setSuggestedModel(data.suggested_model);
      const installed = data.installed_models || [];
      if (installed.includes(data.suggested_model)) setSelectedModel(data.suggested_model);
      else if (installed.length > 0) setSelectedModel(installed[0]);
    } catch (e) { console.log("Hardware info unavailable"); }
  };

  // Auto-detect type as user types
  const handleKeyChange = (val) => {
    setApiKey(val);
    setKeyValid(null);
    const type = detectKeyType(val.trim());
    setDetectedType(type);
    // Auto-set mode when key type is recognized
    if (type === "openai") setMode("online");
    else if (type === "gemini") setMode("gemini");
  };

  // Single unified validate — backend auto-detects too
  const validateKey = async () => {
    if (!apiKey.trim()) return;
    if (detectedType === "unknown") {
      return;  // already showing error in UI
    }
    setValidating(true); setKeyValid(null);
    try {
      const res = await fetch(`${API_URL}/api/validate-key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey.trim() }),
      });
      const data = await res.json();
      if (res.ok && data.valid) {
        setKeyValid(true);
        // Confirm mode from backend response
        if (data.mode) setMode(data.mode);
      } else {
        setKeyValid(false);
      }
    } catch { setKeyValid(false); }
    finally { setValidating(false); }
  };

  const pullModel = async (modelName) => {
    setPullingModel(modelName); setPullStatus(null);
    try {
      const res = await fetch(`${API_URL}/api/pull-model`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: modelName }),
      });
      const data = await res.json();
      if (res.ok) {
        setPullStatus({ success: true, message: `${modelName} downloaded!` });
        setSelectedModel(modelName);
        fetchHardwareInfo();
      } else {
        setPullStatus({ success: false, message: data.detail });
      }
    } catch { setPullStatus({ success: false, message: "Download failed." }); }
    finally { setPullingModel(null); }
  };

  const isOnlineMode   = mode === "online" || mode === "gemini";
  const openaiKey      = mode === "online" ? apiKey.trim() : "";
  const geminiKey      = mode === "gemini" ? apiKey.trim() : "";
  const currentKeyInfo = detectedType ? KEY_INFO[detectedType] : null;
  const currentModel   = availableModels.find(m => m.name === selectedModel);
  const modeLabel      = mode === "online" ? "🟢 OpenAI" : mode === "gemini" ? "🔵 Gemini" : `🔌 Ollama · ${selectedModel}`;

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">

          {/* Brand */}
          <div className="brand">
            <div className="brand-icon">
              <svg viewBox="0 0 40 40" fill="none">
                <circle cx="20" cy="20" r="18" stroke="#fff" strokeWidth="2"/>
                <path d="M12 20 L18 26 L28 14" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            <div>
              <h1 className="brand-title">AI QA Intelligence</h1>
              <p className="brand-subtitle">Decision Platform · {modeLabel}</p>
            </div>
          </div>

          {/* Nav tabs */}
          <nav className="nav">
            <button className={`nav-btn ${activeTab === "regression" ? "active" : ""}`} onClick={() => setActiveTab("regression")}>
              <span className="nav-icon">⚡</span> Regression Optimizer
            </button>
            <button className={`nav-btn ${activeTab === "automation" ? "active" : ""}`} onClick={() => setActiveTab("automation")}>
              <span className="nav-icon">🤖</span> Automation Analyzer
            </button>
          </nav>

          {/* Controls */}
          <div className="header-controls">

            {/* Mode toggle */}
            <div className="mode-toggle-wrap">
              <button className={`mode-btn ${mode === "offline" ? "mode-active" : ""}`}
                onClick={() => { setMode("offline"); setApiKey(""); setDetectedType(null); setKeyValid(null); }}>
                🔌 Offline
              </button>
              <button className={`mode-btn ${isOnlineMode ? "mode-active-online" : ""}`}
                onClick={() => {
                  if (detectedType === "gemini") setMode("gemini");
                  else setMode("online");
                }}>
                🌐 Online
              </button>
            </div>

            {/* Ollama model selector — offline only */}
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
                    {availableModels.map(model => (
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
                              ? <button className={`model-select-btn ${selectedModel === model.name ? "selected" : ""}`}
                                  onClick={() => { setSelectedModel(model.name); setShowModelPanel(false); }}>
                                  {selectedModel === model.name ? "✓ Selected" : "Select"}
                                </button>
                              : <button className="model-pull-btn" onClick={() => pullModel(model.name)} disabled={pullingModel === model.name}>
                                  {pullingModel === model.name ? "⬇ Downloading..." : "⬇ Download"}
                                </button>
                            }
                          </div>
                        </div>
                      </div>
                    ))}
                    {pullStatus && (
                      <div className={`pull-status ${pullStatus.success ? "pull-success" : "pull-error"}`}>
                        {pullStatus.success ? "✓" : "✗"} {pullStatus.message}
                      </div>
                    )}
                    <div className="model-panel-note">
                      💡 Download once — stays on your PC. Or run <code>ollama pull {selectedModel}</code>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* API Key Bar — shown when Online mode selected */}
        {isOnlineMode && (
          <div className="api-key-bar">
            <div className="api-key-inner">

              {/* Auto-detected key badge */}
              {currentKeyInfo && (
                <span className="key-type-badge" style={{ background: currentKeyInfo.bg, color: currentKeyInfo.color, borderColor: currentKeyInfo.border }}>
                  {currentKeyInfo.icon} {currentKeyInfo.label}
                </span>
              )}
              {!currentKeyInfo && (
                <span className="api-key-label">🔑 API Key</span>
              )}

              {/* Key input */}
              <div className={`api-key-input-wrap ${detectedType === "unknown" ? "input-error" : ""}`}>
                <input
                  type={showKey ? "text" : "password"}
                  className="api-key-input"
                  placeholder="Paste OpenAI (sk-...) or Gemini (AIza...) key — auto-detected"
                  value={apiKey}
                  onChange={(e) => handleKeyChange(e.target.value)}
                />
                <button className="key-toggle-btn" onClick={() => setShowKey(!showKey)}>
                  {showKey ? "🙈" : "👁️"}
                </button>
              </div>

              {/* Validate button */}
              <button className="validate-btn" onClick={validateKey}
                disabled={validating || !apiKey || detectedType === "unknown" || detectedType === null}>
                {validating ? "Checking..." : "Validate"}
              </button>

              {/* Validation result */}
              {keyValid === true  && <span className="key-status valid">✓ Valid · {detectedType === "gemini" ? "Gemini" : "OpenAI"}</span>}
              {keyValid === false && <span className="key-status invalid">✗ Invalid key</span>}
              {detectedType === "unknown" && <span className="key-status invalid">✗ Unrecognized format</span>}

              {/* Hint text */}
              <span className="api-key-note">
                {detectedType === "openai" && "OpenAI key detected (sk-...) · platform.openai.com/api-keys"}
                {detectedType === "gemini" && "Gemini key detected (AIza...) · aistudio.google.com/app/apikey"}
                {!detectedType && "Paste your key — type auto-detected from format"}
              </span>
            </div>
          </div>
        )}
      </header>

      <main className="main">
        {activeTab === "regression"
          ? <RegressionOptimizer mode={mode} openaiKey={openaiKey} geminiKey={geminiKey} keyValid={keyValid} selectedModel={selectedModel} />
          : <AutomationAnalyzer  mode={mode} openaiKey={openaiKey} geminiKey={geminiKey} keyValid={keyValid} selectedModel={selectedModel} />
        }
      </main>

      <footer className="footer">
        <p>AI QA Decision Intelligence Platform v1.0 · {modeLabel}</p>
      </footer>
    </div>
  );
}