/* Client-side logic for Groww Pulse Control Tower (Phase 7) */

document.addEventListener("DOMContentLoaded", () => {
    initApp();
});

let currentRunsData = [];
let isRunning = false;

function initApp() {
    setupEventListeners();
    loadStatus();
    loadClusters();
}

function setupEventListeners() {
    const triggerBtn = document.getElementById("trigger-run-btn");
    if (triggerBtn) {
        triggerBtn.addEventListener("click", triggerPulseRun);
    }

    const refreshPlotBtn = document.getElementById("refresh-plot-btn");
    if (refreshPlotBtn) {
        refreshPlotBtn.addEventListener("click", loadClusters);
    }

    const refreshLedgerBtn = document.getElementById("refresh-ledger-btn");
    if (refreshLedgerBtn) {
        refreshLedgerBtn.addEventListener("click", loadStatus);
    }
}

function showToast(msg, type = "success") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `<span>${type === 'error' ? '❌' : '⚡'} ${msg}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

async function loadStatus() {
    try {
        const weekInput = document.getElementById("week-select");
        const weekVal = weekInput ? weekInput.value.trim() : "";
        
        let url = "/api/status?product=groww";
        if (weekVal) url += `&iso_week=${weekVal}`;

        const res = await fetch(url);
        const data = await res.json();
        
        if (data.status === "success" && data.runs) {
            currentRunsData = data.runs;
            renderLedgerTable(data.runs);
            updateKPICards(data.runs);
            
            // If we have a completed run with a report, load themes into drawer
            const latestCompleted = data.runs.find(r => r.status === "completed" || r.report);
            if (latestCompleted && latestCompleted.report) {
                renderThemes(latestCompleted.report);
            } else if (data.runs.length > 0 && data.runs[0].report) {
                renderThemes(data.runs[0].report);
            }
        }
    } catch (e) {
        console.error("Error loading status:", e);
        showToast("Failed to fetch ledger audit history.", "error");
    }
}

function updateKPICards(runs) {
    const totalReviewsEl = document.getElementById("kpi-reviews");
    const totalThemesEl = document.getElementById("kpi-themes");
    const stateEl = document.getElementById("kpi-state");
    const idempEl = document.getElementById("kpi-idemp");

    if (runs.length > 0) {
        const latest = runs[0];
        totalReviewsEl.textContent = latest.review_count || "—";
        
        if (latest.report && latest.report.themes) {
            totalThemesEl.textContent = latest.report.themes.length;
        } else {
            totalThemesEl.textContent = "—";
        }

        // Update pipeline state KPI card
        if (stateEl) {
            const s = latest.status || "unknown";
            stateEl.textContent = s.toUpperCase().replace("_", " ");
            if (s === "completed") stateEl.style.color = "var(--neon-green)";
            else if (s === "failed") stateEl.style.color = "var(--neon-pink)";
            else stateEl.style.color = "var(--neon-cyan)";
        }

        const weekInput = document.getElementById("week-select");
        const targetWeek = weekInput ? weekInput.value.trim() : "2026-W27";
        const completedWeekRun = runs.find(r => r.iso_week === targetWeek && r.status === "completed");
        
        if (completedWeekRun) {
            idempEl.textContent = "LOCKED";
            idempEl.style.color = "var(--neon-green)";
        } else {
            idempEl.textContent = "READY";
            idempEl.style.color = "var(--neon-cyan)";
        }
    }
}

function renderLedgerTable(runs) {
    const tbody = document.getElementById("ledger-tbody");
    if (!tbody) return;

    if (runs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center">No ledger records found for Groww. Click 'Trigger Pulse Run' above!</td></tr>`;
        return;
    }

    tbody.innerHTML = runs.map(r => {
        const docDeliv = r.deliveries.find(d => d.channel === "google_doc");
        const mailDeliv = r.deliveries.find(d => d.channel === "gmail");

        const docLink = docDeliv 
            ? `<a href="${docDeliv.url}" target="_blank" class="btn-link">📄 Open Doc Section</a>` 
            : `<span class="text-muted">None</span>`;
            
        const mailLink = mailDeliv 
            ? `<a href="${mailDeliv.url}" target="_blank" class="btn-link btn-link-mail">📧 Open Gmail Draft</a>` 
            : `<span class="text-muted">None</span>`;

        let statusBadge = `<span class="badge-sub">${r.status}</span>`;
        if (r.status === "completed") statusBadge = `<span class="status-pill status-ready">COMPLETED</span>`;
        if (r.status === "dry_run") statusBadge = `<span class="status-pill status-running">DRY RUN</span>`;
        if (r.status === "failed") statusBadge = `<span class="status-pill status-error">FAILED</span>`;

        return `
            <tr>
                <td><strong>${r.iso_week}</strong></td>
                <td><span class="code-pill">${r.run_id.slice(0, 8)}...</span></td>
                <td>${statusBadge}</td>
                <td>${r.review_count}</td>
                <td>${new Date(r.started_at).toLocaleString()}</td>
                <td>${docLink}</td>
                <td>${mailLink}</td>
                <td><button class="btn-secondary btn-inspect" onclick="inspectRun('${r.run_id}')">🔍 Inspect</button></td>
            </tr>
        `;
    }).join("");
}

window.inspectRun = function(runId) {
    const run = currentRunsData.find(r => r.run_id === runId);
    if (run && run.report) {
        renderThemes(run.report);
        showToast(`Loaded theme insights for Run ID: ${runId.slice(0, 8)}...`);
    } else {
        showToast(`No report JSON available for Run ID: ${runId.slice(0, 8)}...`, "error");
    }
};

function renderThemes(report) {
    const listContainer = document.getElementById("theme-accordion-list");
    if (!listContainer || !report || !report.themes) return;

    if (report.themes.length === 0) {
        listContainer.innerHTML = `<div class="empty-state">No themes identified in this run.</div>`;
        return;
    }

    listContainer.innerHTML = report.themes.map((th, index) => {
        const quotesHtml = (th.quotes || []).map((q, qi) => `
            <div class="quote-box">
                <span>"${q}"</span>
                <button class="btn-copy" data-quote-index="${index}-${qi}">📋 Copy</button>
            </div>
        `).join("");

        const actionsHtml = (th.action_ideas || []).map(act => `
            <div class="action-idea-item">
                <div class="action-title">🛠️ ${act.title}</div>
                <div class="action-detail">${act.detail}</div>
            </div>
        `).join("");

        return `
            <div class="theme-card ${index === 0 ? 'expanded' : ''}" onclick="toggleThemeCard(this, event)">
                <div class="theme-card-header">
                    <div class="theme-title">
                        <span>🏷️</span>
                        <span>${th.theme_name}</span>
                    </div>
                    <div class="theme-meta">
                        <span class="badge-count">${(th.quotes || []).length} Quotes</span>
                        <span class="badge-action">${(th.action_ideas || []).length} Actions</span>
                    </div>
                </div>
                <div class="theme-drawer" onclick="event.stopPropagation()">
                    <div class="drawer-section-title">Verified Customer Quotes (Exact Match)</div>
                    ${quotesHtml || '<div class="text-muted">No quotes passed verification.</div>'}
                    
                    <div class="drawer-section-title" style="margin-top: 8px;">Recommended Engineering Tasks</div>
                    ${actionsHtml || '<div class="text-muted">No action tasks generated.</div>'}
                </div>
            </div>
        `;
    }).join("");

    // Attach click handlers for copy buttons using data attributes
    listContainer.querySelectorAll('.btn-copy[data-quote-index]').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            const [themeIdx, quoteIdx] = this.dataset.quoteIndex.split('-').map(Number);
            const quoteText = report.themes[themeIdx]?.quotes?.[quoteIdx] || '';
            navigator.clipboard.writeText(quoteText);
            const origText = this.innerHTML;
            this.innerHTML = "✅ Copied!";
            setTimeout(() => { this.innerHTML = origText; }, 2000);
        });
    });
}

window.toggleThemeCard = function(cardEl, event) {
    if (event.target.tagName === 'BUTTON') return;
    cardEl.classList.toggle("expanded");
};

async function loadClusters(retryCount = 0) {
    const plotBox = document.getElementById("cluster-plot-container");
    if (!plotBox) return;

    try {
        const weekInput = document.getElementById("week-select");
        const weekVal = weekInput ? weekInput.value.trim() : "";
        let url = "/api/clusters?product=groww";
        if (weekVal) url += `&iso_week=${weekVal}`;

        const res = await fetch(url);
        if (!res.ok) {
            throw new Error(`Server returned ${res.status}: ${res.statusText}`);
        }
        const data = await res.json();

        if (data.status === "success" && data.points && data.points.length > 0) {
            renderClusterPlot(data.points);
        } else {
            plotBox.innerHTML = `<div class="loading-spinner">No cluster data available.</div>`;
        }
    } catch (e) {
        console.error("Error loading clusters:", e);
        // If Plotly CDN hasn't loaded yet, retry up to 3 times with backoff
        if (e.message && e.message.includes("Plotly") && retryCount < 3 && !window.__plotlyFailed) {
            const delay = 1000 * Math.pow(2, retryCount);
            console.warn(`Plotly not ready. Retrying in ${delay}ms (attempt ${retryCount + 1}/3)...`);
            plotBox.innerHTML = `<div class="loading-spinner">Waiting for Plotly library to load...</div>`;
            setTimeout(() => loadClusters(retryCount + 1), delay);
            return;
        }
        plotBox.innerHTML = `<div class="loading-spinner" style="color: var(--neon-pink);">Failed to render cluster plot. ${e.message || 'Check console for details.'}</div>`;
    }
}

function renderClusterPlot(points) {
    if (typeof Plotly === "undefined") {
        throw new Error("Plotly CDN not loaded. Cannot render scatter plot.");
    }

    // Group points by cluster
    const clusterMap = {};
    const colorPalette = ["#00F0FF", "#8A2BE2", "#00FF88", "#FF007F", "#FFB800", "#38BDF8", "#F43F5E"];

    points.forEach(p => {
        if (!clusterMap[p.cluster_name]) {
            clusterMap[p.cluster_name] = {
                x: [], y: [], text: [], ratings: [], fullTexts: [],
                name: p.cluster_name,
                mode: 'markers',
                type: 'scatter',
                marker: { size: 12, opacity: 0.85, line: { color: '#FFFFFF', width: 1 } },
                hovertemplate: '<b>Rating:</b> %{customdata}⭐<br><b>Snippet:</b> %{text}<extra>%{fullData.name}</extra>'
            };
        }
        clusterMap[p.cluster_name].x.push(p.x);
        clusterMap[p.cluster_name].y.push(p.y);
        clusterMap[p.cluster_name].text.push(p.text);
        clusterMap[p.cluster_name].customdata = clusterMap[p.cluster_name].customdata || [];
        clusterMap[p.cluster_name].customdata.push(p.rating);
    });

    const traces = Object.values(clusterMap).map((trace, idx) => {
        trace.marker.color = colorPalette[idx % colorPalette.length];
        return trace;
    });

    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        margin: { t: 20, r: 20, b: 30, l: 30 },
        font: { color: '#94A3B8', family: 'Inter' },
        showlegend: true,
        legend: { font: { size: 11, color: '#F8FAFC' }, orientation: 'h', y: -0.15 },
        xaxis: { showgrid: true, gridcolor: 'rgba(255, 255, 255, 0.05)', zeroline: false },
        yaxis: { showgrid: true, gridcolor: 'rgba(255, 255, 255, 0.05)', zeroline: false },
        hoverlabel: { bgcolor: '#1E293B', font: { color: '#FFF' }, bordercolor: '#00F0FF' }
    };

    const config = { responsive: true, displayModeBar: false };
    // Clear loading spinner before Plotly renders into the container
    const container = document.getElementById("cluster-plot-container");
    if (container) container.innerHTML = "";
    Plotly.newPlot("cluster-plot-container", traces, layout, config);
}

async function pollJobUntilDone(jobId, maxPollMs = 300000) {
    const pollInterval = 3000;
    const start = Date.now();

    return new Promise((resolve, reject) => {
        const poll = async () => {
            try {
                const res = await fetch(`/api/job/${jobId}`);
                if (!res.ok) {
                    reject(new Error(`Polling failed: ${res.status}`));
                    return;
                }
                const data = await res.json();

                if (data.status === "running") {
                    if (Date.now() - start > maxPollMs) {
                        reject(new Error("Pipeline timed out after 5 minutes."));
                        return;
                    }
                    setTimeout(poll, pollInterval);
                } else if (data.status === "success") {
                    resolve(data.result);
                } else {
                    reject(new Error(data.detail || "Pipeline failed with unknown error."));
                }
            } catch (e) {
                reject(e);
            }
        };
        setTimeout(poll, pollInterval);
    });
}

async function triggerPulseRun() {
    if (isRunning) return;
    isRunning = true;

    const triggerBtn = document.getElementById("trigger-run-btn");
    const statusText = document.getElementById("pipeline-status-text");
    const weekInput = document.getElementById("week-select");
    const dryRunToggle = document.getElementById("dry-run-toggle");

    const weekVal = weekInput ? weekInput.value.trim() : "2026-W27";
    const isDryRun = dryRunToggle ? dryRunToggle.checked : false;

    if (triggerBtn) triggerBtn.disabled = true;
    if (statusText) {
        statusText.textContent = "EXECUTING PIPELINE...";
        statusText.className = "status-pill status-running";
    }

    // Simulate UI progress animation across the 6 pipeline stages
    const steps = ["ingest", "embed", "cluster", "llm", "validate", "deliver"];
    steps.forEach(s => {
        const el = document.getElementById(`step-${s}`);
        if (el) el.className = "step";
    });

    let stepIdx = 0;
    const progressInterval = setInterval(() => {
        if (stepIdx < steps.length) {
            const el = document.getElementById(`step-${steps[stepIdx]}`);
            if (el) el.classList.add("active");
            if (stepIdx > 0) {
                const prevEl = document.getElementById(`step-${steps[stepIdx - 1]}`);
                if (prevEl) {
                    prevEl.classList.remove("active");
                    prevEl.classList.add("completed");
                }
            }
            stepIdx++;
        }
    }, 800);

    try {
        showToast(`Initiating ${isDryRun ? 'Dry-Run' : 'Live'} Pulse Pipeline for Groww (${weekVal})...`);

        // Step 1: Submit the job
        const res = await fetch("/api/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                product: "groww",
                iso_week: weekVal,
                dry_run: isDryRun,
                email_mode: "draft"
            })
        });

        const submitData = await res.json();

        if (submitData.status !== "accepted" || !submitData.job_id) {
            throw new Error(submitData.detail || "Failed to submit pipeline job.");
        }

        showToast(`Pipeline job submitted (ID: ${submitData.job_id.slice(0, 8)}...). Waiting for results...`);

        // Step 2: Poll until done
        const runRes = await pollJobUntilDone(submitData.job_id);

        clearInterval(progressInterval);

        // Mark all steps completed
        steps.forEach(s => {
            const el = document.getElementById(`step-${s}`);
            if (el) {
                el.classList.remove("active");
                el.classList.add("completed");
            }
        });

        if (statusText) {
            statusText.textContent = "COMPLETED";
            statusText.className = "status-pill status-ready";
        }

        // "already_completed" is what the orchestrator returns for idempotent no-ops
        if (runRes.status === "already_completed") {
            showToast(`Idempotent No-Op: Run already completed for ${weekVal}.`, "success");
        } else {
            showToast(`Pipeline execution successful! Run ID: ${runRes.run_id.slice(0, 8)}...`, "success");
        }
        // Reload dashboard data
        await loadStatus();
        await loadClusters();

    } catch (e) {
        clearInterval(progressInterval);
        console.error("Run error:", e);
        // Show error state in pipeline telemetry
        steps.forEach(s => {
            const el = document.getElementById(`step-${s}`);
            if (el) el.classList.remove("active");
        });
        if (statusText) {
            statusText.textContent = "ERROR";
            statusText.className = "status-pill status-error";
        }
        showToast(e.message || "Error executing pipeline run. Check server logs.", "error");
    } finally {
        isRunning = false;
        if (triggerBtn) triggerBtn.disabled = false;
    }
}
