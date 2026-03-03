import { useState } from "react";
import RegressionOptimizer from "./components/RegressionOptimizer";
import AutomationAnalyzer from "./components/AutomationAnalyzer";
import "./index.css";

export default function App() {
  const [activeTab, setActiveTab] = useState("regression");

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div className="brand">
            <div className="brand-icon">
              {/* <svg viewBox="0 0 40 40" fill="none">
                <circle cx="20" cy="20" r="18" stroke="#00D4FF" strokeWidth="2" />
                <path d="M12 20 L18 26 L28 14" stroke="#00D4FF" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
                <circle cx="20" cy="20" r="4" fill="#00D4FF" opacity="0.3"/>
              </svg> */}
            </div>
            <div>
              <h1 className="brand-title">AI QA Intelligence</h1>
            
            </div>
          </div>
          <nav className="nav">
            <button
              className={`nav-btn ${activeTab === "regression" ? "active" : ""}`}
              onClick={() => setActiveTab("regression")}
            >
              <span className="nav-icon">⚡</span>
              Regression Optimizer
            </button>
            <button
              className={`nav-btn ${activeTab === "automation" ? "active" : ""}`}
              onClick={() => setActiveTab("automation")}
            >
              <span className="nav-icon">🤖</span>
              Automation Analyzer
            </button>
          </nav>
        </div>
      </header>

      <main className="main">
        {activeTab === "regression" ? <RegressionOptimizer /> : <AutomationAnalyzer />}
      </main>

      <footer className="footer">
      </footer>
    </div>
  );
}
