import { useState, useRef, useEffect } from "react"

const API_URL = "http://localhost:8000"

const MAX_HISTORY = 2

export default function App() {
  const [query, setQuery]             = useState("")
  const [results, setResults]         = useState([])
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState("")
  const [activeOnly, setActiveOnly]   = useState(false)
  const [searched, setSearched]       = useState(false)
  const [minScore, setMinScore]       = useState(0.0)
  const [history, setHistory]         = useState([])
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [activeHistoryIdx, setActiveHistoryIdx] = useState(null)

  // votes: { [chunk_id]: "up" | "down" }
  const [votes, setVotes] = useState({})
  // submitting: Set of chunk_ids currently being submitted
  const [submitting, setSubmitting] = useState(new Set())

  const inputRef = useRef(null)

  useEffect(() => { inputRef.current?.focus() }, [])

  const displayResults = activeHistoryIdx !== null
    ? history[activeHistoryIdx]?.results || []
    : results

  const displayQuery = activeHistoryIdx !== null
    ? history[activeHistoryIdx]?.query || ""
    : query

  const filtered = displayResults.filter(r => !activeOnly || r.api_status === "ACTIVE")

  async function handleSearch() {
    if (!query.trim()) return
    setLoading(true)
    setError("")
    setResults([])
    setSearched(true)
    setActiveHistoryIdx(null)

    try {
      const res = await fetch(`${API_URL}/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, top_k: 50, mode: "graph", min_score: minScore })
      })
      const data = await res.json()
      const newResults = data.results || []
      setResults(newResults)

      setHistory(prev => {
        const entry = {
          query, minScore, results: newResults,
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        }
        return [entry, ...prev].slice(0, MAX_HISTORY)
      })
    } catch {
      setError("Cannot reach API — is FastAPI running on port 8000?")
    } finally {
      setLoading(false)
    }
  }

  async function handleVote(chunkId, vote) {
    // Optimistic update
    setVotes(v => ({ ...v, [chunkId]: vote }))
    setSubmitting(s => new Set(s).add(chunkId))

    try {
      await fetch(`${API_URL}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chunk_id: chunkId, vote, query: displayQuery })
      })
    } catch (e) {
      console.error("[FEEDBACK]", e)
      // Revert on failure
      setVotes(v => { const n = { ...v }; delete n[chunkId]; return n })
    } finally {
      setSubmitting(s => { const n = new Set(s); n.delete(chunkId); return n })
    }
  }

  function handleHistoryClick(idx) {
    setActiveHistoryIdx(idx)
    setSidebarOpen(false)
  }

  function handleBackToCurrent() {
    setActiveHistoryIdx(null)
  }

  return (
    <div style={{
      minHeight: "100vh", background: "#0c0c10", color: "#e8e8f0",
      fontFamily: "'IBM Plex Mono', 'Courier New', monospace",
      position: "relative",
    }}>

      <div style={{
        position: "fixed", top: 0, left: "50%", transform: "translateX(-50%)",
        width: 800, height: 400, borderRadius: "50%",
        background: "radial-gradient(ellipse, rgba(0,120,255,0.08) 0%, transparent 70%)",
        pointerEvents: "none"
      }} />

      {/* ── History sidebar ── */}
      <>
        {history.length > 0 && (
          <button onClick={() => setSidebarOpen(o => !o)} style={{
            position: "fixed", right: sidebarOpen ? 260 : 0, top: "50%",
            transform: "translateY(-50%)",
            background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.08)",
            borderRadius: "6px 0 0 6px",
            color: "#5a5a70", cursor: "pointer",
            padding: "12px 6px", fontSize: 11,
            fontFamily: "inherit", letterSpacing: "0.06em",
            writingMode: "vertical-rl", textOrientation: "mixed",
            transition: "right 0.25s ease", zIndex: 100,
          }}>
            {sidebarOpen ? "▶ hide" : "◀ history"}
          </button>
        )}

        <div style={{
          position: "fixed", right: sidebarOpen ? 0 : -260, top: 0,
          width: 260, height: "100vh", background: "#0e0e14",
          borderLeft: "1px solid rgba(255,255,255,0.06)",
          transition: "right 0.25s ease", zIndex: 99,
          display: "flex", flexDirection: "column",
          padding: "24px 0", overflowY: "auto",
        }}>
          <div style={{
            padding: "0 20px 16px", fontSize: 10, color: "#3a3a50",
            letterSpacing: "0.1em", textTransform: "uppercase",
            borderBottom: "1px solid rgba(255,255,255,0.04)", marginBottom: 12,
          }}>
            Recent searches
          </div>

          {history.map((item, idx) => (
            <button key={idx} onClick={() => handleHistoryClick(idx)} style={{
              display: "block", width: "100%", textAlign: "left",
              padding: "12px 20px",
              background: activeHistoryIdx === idx ? "rgba(0,120,255,0.08)" : "transparent",
              border: "none",
              borderLeft: `2px solid ${activeHistoryIdx === idx ? "#4a9eff" : "transparent"}`,
              cursor: "pointer", transition: "all 0.15s",
            }}
              onMouseEnter={e => { if (activeHistoryIdx !== idx) e.currentTarget.style.background = "rgba(255,255,255,0.03)" }}
              onMouseLeave={e => { if (activeHistoryIdx !== idx) e.currentTarget.style.background = "transparent" }}
            >
              <div style={{ fontSize: 12, color: "#c8c8d8", marginBottom: 4, fontFamily: "inherit" }}>
                {item.query}
              </div>
              <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                <span style={{ fontSize: 10, color: "#3a3a50", padding: "1px 6px", borderRadius: 3, background: "rgba(255,255,255,0.04)" }}>
                  {item.results.length} results
                </span>
                <span style={{ fontSize: 10, color: "#2a2a40", marginLeft: "auto" }}>{item.timestamp}</span>
              </div>
              {item.minScore > 0 && (
                <div style={{ fontSize: 10, color: "#2a4a6a", marginTop: 3 }}>
                  score ≥ {item.minScore.toFixed(2)}
                </div>
              )}
            </button>
          ))}
        </div>
      </>

      {/* ── Main content ── */}
      <div style={{ maxWidth: 860, margin: "0 auto", padding: "60px 24px 80px" }}>

        <div style={{ marginBottom: 48 }}>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 8,
            background: "rgba(0,120,255,0.1)", border: "1px solid rgba(0,120,255,0.2)",
            borderRadius: 4, padding: "4px 10px", marginBottom: 20,
            fontSize: 11, color: "#4a9eff", letterSpacing: "0.12em", textTransform: "uppercase"
          }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#4a9eff",
              animation: "pulse 2s infinite", display: "inline-block" }} />
            S/4HANA API Catalog
          </div>
          <h1 style={{
            fontSize: "clamp(32px,5vw,52px)", fontWeight: 700, margin: 0,
            letterSpacing: "-0.03em", lineHeight: 1.1,
            background: "linear-gradient(135deg, #fff 0%, #4a9eff 60%, #00d4aa 100%)",
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent"
          }}>
            SAP API Explorer
          </h1>
          <p style={{ color: "#5a5a70", marginTop: 10, fontSize: 13, letterSpacing: "0.04em" }}>
            229 S/4HANA APIs · 76,097 parameters indexed
          </p>
        </div>

        {/* Search bar */}
        <div style={{
          display: "flex", gap: 8, marginBottom: 16,
          background: "rgba(255,255,255,0.03)",
          border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: 8, padding: 4,
        }}>
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSearch()}
            placeholder="vat · routing · withholding tax · sales order..."
            style={{
              flex: 1, background: "transparent", border: "none", outline: "none",
              color: "#e8e8f0", fontSize: 15, padding: "10px 14px",
              fontFamily: "inherit", letterSpacing: "0.02em"
            }}
          />
          <button onClick={handleSearch} disabled={loading} style={{
            padding: "10px 24px", background: loading ? "rgba(0,120,255,0.3)" : "#0070f3",
            color: "white", border: "none", borderRadius: 6, cursor: loading ? "default" : "pointer",
            fontSize: 13, fontFamily: "inherit", letterSpacing: "0.06em",
            textTransform: "uppercase", fontWeight: 600, transition: "background 0.2s"
          }}>
            {loading ? "···" : "Search"}
          </button>
        </div>

        {/* Controls */}
        <div style={{ display: "flex", gap: 6, marginBottom: 36, flexWrap: "wrap", alignItems: "center" }}>
          <button onClick={() => setActiveOnly(!activeOnly)} style={{
            padding: "5px 14px", borderRadius: 4, cursor: "pointer",
            background: activeOnly ? "rgba(0,212,100,0.12)" : "transparent",
            color: activeOnly ? "#00d464" : "#5a5a70",
            border: `1px solid ${activeOnly ? "rgba(0,212,100,0.25)" : "rgba(255,255,255,0.06)"}`,
            fontSize: 12, fontFamily: "inherit", letterSpacing: "0.04em", transition: "all 0.15s"
          }}>
            {activeOnly ? "● Active only" : "○ All status"}
          </button>

          <div style={{ width: 1, height: 20, background: "rgba(255,255,255,0.08)", margin: "0 4px" }} />

          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 11, color: "#5a5a70", letterSpacing: "0.04em", whiteSpace: "nowrap" }}>
              score ≥ {minScore.toFixed(2)}
            </span>
            <input type="range" min={0} max={1} step={0.05} value={minScore}
              onChange={e => setMinScore(parseFloat(e.target.value))}
              style={{ width: 80, accentColor: "#4a9eff", cursor: "pointer" }}
            />
            {minScore > 0 && (
              <button onClick={() => setMinScore(0.0)} style={{
                background: "none", border: "none", color: "#3a3a50",
                cursor: "pointer", fontSize: 11, padding: "0 2px", fontFamily: "inherit"
              }}>✕</button>
            )}
          </div>

          {(searched || activeHistoryIdx !== null) && !loading && (
            <span style={{ marginLeft: "auto", fontSize: 11, color: "#3a3a50", letterSpacing: "0.06em" }}>
              {filtered.length} / {displayResults.length} results
            </span>
          )}
        </div>

        {/* History banner */}
        {activeHistoryIdx !== null && (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "10px 16px", marginBottom: 20,
            background: "rgba(0,120,255,0.06)", border: "1px solid rgba(0,120,255,0.12)",
            borderRadius: 6, fontSize: 12,
          }}>
            <span style={{ color: "#4a9eff" }}>
              ◷ Showing stored results for "{history[activeHistoryIdx]?.query}"
            </span>
            <button onClick={handleBackToCurrent} style={{
              background: "none", border: "none", color: "#4a9eff",
              cursor: "pointer", fontSize: 11, fontFamily: "inherit", letterSpacing: "0.04em"
            }}>← back to current</button>
          </div>
        )}

        {error && (
          <div style={{
            padding: "12px 16px", background: "rgba(255,50,50,0.08)",
            border: "1px solid rgba(255,50,50,0.15)", borderRadius: 6,
            color: "#ff6b6b", fontSize: 13, marginBottom: 24
          }}>{error}</div>
        )}

        {loading && (
          <div style={{ textAlign: "center", padding: 60, color: "#3a3a50", fontSize: 13 }}>
            <div style={{ fontSize: 24, marginBottom: 12, opacity: 0.5 }}>⬡</div>
            Searching...
          </div>
        )}

        {/* Results */}
        {!loading && filtered.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {filtered.map((r) => {
              const voted      = votes[r.id]
              const isSubmitting = submitting.has(r.id)

              return (
                <div key={r.id} style={{
                  background: "rgba(255,255,255,0.02)",
                  border: "1px solid rgba(255,255,255,0.06)",
                  borderRadius: 8, padding: "16px 20px",
                  transition: "border-color 0.15s, background 0.15s",
                }}
                  onMouseEnter={e => {
                    e.currentTarget.style.borderColor = "rgba(0,120,255,0.2)"
                    e.currentTarget.style.background = "rgba(255,255,255,0.03)"
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.borderColor = "rgba(255,255,255,0.06)"
                    e.currentTarget.style.background = "rgba(255,255,255,0.02)"
                  }}
                >
                  {/* Top row */}
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontWeight: 700, fontSize: 14, color: "#d8d8e8" }}>
                        {r.api_title || "—"}
                      </span>
                      <span style={{
                        fontSize: 10, padding: "2px 7px", borderRadius: 3,
                        background: r.api_status === "ACTIVE" ? "rgba(0,212,100,0.1)" : "rgba(255,80,80,0.1)",
                        color: r.api_status === "ACTIVE" ? "#00d464" : "#ff6b6b",
                        border: `1px solid ${r.api_status === "ACTIVE" ? "rgba(0,212,100,0.2)" : "rgba(255,80,80,0.2)"}`,
                        letterSpacing: "0.06em", textTransform: "uppercase"
                      }}>
                        {r.api_status || "?"}
                      </span>
                    </div>

                    {/* Score + route + vote buttons */}
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      {r.score > 0 && (
                        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          <div style={{ width: 40, height: 3, borderRadius: 2, background: "rgba(255,255,255,0.06)", overflow: "hidden" }}>
                            <div style={{
                              width: `${Math.round(r.score * 100)}%`, height: "100%", borderRadius: 2,
                              background: r.score > 0.7 ? "#4a9eff" : r.score > 0.4 ? "#7ab8ff" : "#2a5a8a"
                            }} />
                          </div>
                          <span style={{ fontSize: 11, color: "#2a5a8a" }}>{r.score.toFixed(2)}</span>
                        </div>
                      )}
                      <span style={{
                        fontSize: 10, padding: "2px 7px", borderRadius: 3,
                        background: "rgba(255,255,255,0.04)", color: "#3a3a50", letterSpacing: "0.06em"
                      }}>
                        {r.route}
                      </span>

                      {/* 👍 👎 feedback buttons */}
                      <div style={{ display: "flex", gap: 4, marginLeft: 4 }}>
                        <button
                          onClick={() => !voted && !isSubmitting && handleVote(r.id, "up")}
                          title="Relevant result"
                          style={{
                            width: 26, height: 26, borderRadius: 4,
                            border: `1px solid ${voted === "up" ? "rgba(0,212,100,0.4)" : "rgba(255,255,255,0.08)"}`,
                            background: voted === "up" ? "rgba(0,212,100,0.15)" : "rgba(255,255,255,0.03)",
                            color: voted === "up" ? "#00d464" : "#3a3a50",
                            cursor: voted || isSubmitting ? "default" : "pointer",
                            fontSize: 12, display: "flex", alignItems: "center", justifyContent: "center",
                            transition: "all 0.2s",
                            opacity: isSubmitting ? 0.5 : 1,
                          }}
                        >
                          ↑
                        </button>
                        <button
                          onClick={() => !voted && !isSubmitting && handleVote(r.id, "down")}
                          title="Not relevant"
                          style={{
                            width: 26, height: 26, borderRadius: 4,
                            border: `1px solid ${voted === "down" ? "rgba(255,80,80,0.4)" : "rgba(255,255,255,0.08)"}`,
                            background: voted === "down" ? "rgba(255,80,80,0.12)" : "rgba(255,255,255,0.03)",
                            color: voted === "down" ? "#ff6b6b" : "#3a3a50",
                            cursor: voted || isSubmitting ? "default" : "pointer",
                            fontSize: 12, display: "flex", alignItems: "center", justifyContent: "center",
                            transition: "all 0.2s",
                            opacity: isSubmitting ? 0.5 : 1,
                          }}
                        >
                          ↓
                        </button>
                      </div>
                    </div>
                  </div>

                  <div style={{ fontSize: 11, color: "#2a4a6a", marginBottom: r.param_name ? 10 : 0, letterSpacing: "0.02em" }}>
                    {r.api_name}
                  </div>

                  {r.param_name && (
                    <div style={{
                      background: "rgba(0,120,255,0.05)", border: "1px solid rgba(0,120,255,0.1)",
                      borderRadius: 5, padding: "8px 12px", fontSize: 12
                    }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        <span style={{ color: "#7ab8ff", fontWeight: 600 }}>{r.param_name}</span>
                        {r.param_type && <span style={{ color: "#3a5a7a", fontSize: 11 }}>{r.param_type}</span>}
                        {r.method && (
                          <span style={{
                            fontSize: 10, padding: "1px 6px", borderRadius: 3,
                            background: r.method === "POST" ? "rgba(255,140,0,0.1)" : r.method === "GET" ? "rgba(0,200,100,0.1)" : "rgba(255,255,255,0.05)",
                            color: r.method === "POST" ? "#ff8c00" : r.method === "GET" ? "#00c864" : "#5a5a70",
                            letterSpacing: "0.06em"
                          }}>
                            {r.method}
                          </span>
                        )}
                        {r.required === "True" && (
                          <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3, background: "rgba(255,80,80,0.1)", color: "#ff6b6b", letterSpacing: "0.06em" }}>
                            required
                          </span>
                        )}
                      </div>
                      {r.description && (
                        <div style={{ color: "#5a6a7a", marginTop: 5, fontSize: 11, lineHeight: 1.5 }}>
                          {r.description}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {!loading && (searched || activeHistoryIdx !== null) && filtered.length === 0 && (
          <div style={{ textAlign: "center", padding: "60px 0", color: "#3a3a50" }}>
            <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.3 }}>◎</div>
            <div style={{ fontSize: 13 }}>No results for "{displayQuery}"</div>
            {minScore > 0 && (
              <div style={{ fontSize: 11, marginTop: 8, color: "#2a2a40" }}>
                Try lowering the score threshold (currently {minScore.toFixed(2)})
              </div>
            )}
          </div>
        )}

        {!searched && activeHistoryIdx === null && (
          <div style={{ marginTop: 40 }}>
            <div style={{ fontSize: 11, color: "#3a3a50", letterSpacing: "0.08em", marginBottom: 12, textTransform: "uppercase" }}>
              Try searching for
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {["vat", "routing", "withholding tax", "sales order", "material group", "billing", "gst"].map(s => (
                <button key={s} onClick={() => { setQuery(s); setTimeout(handleSearch, 0) }}
                  style={{
                    padding: "5px 12px", background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.07)", borderRadius: 4,
                    color: "#4a4a60", fontSize: 12, cursor: "pointer", fontFamily: "inherit",
                    transition: "all 0.15s"
                  }}
                  onMouseEnter={e => { e.currentTarget.style.color = "#7ab8ff"; e.currentTarget.style.borderColor = "rgba(0,120,255,0.2)" }}
                  onMouseLeave={e => { e.currentTarget.style.color = "#4a4a60"; e.currentTarget.style.borderColor = "rgba(255,255,255,0.07)" }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

      </div>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #0c0c10; }
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.4; transform: scale(0.8); }
        }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
      `}</style>
    </div>
  )
}