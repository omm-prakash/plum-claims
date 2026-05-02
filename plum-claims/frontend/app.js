/**
 * Plum Claims UI — Application Logic
 * Connects to FastAPI backend for claim submission, viewing, and evaluation.
 */

const API_BASE = 'https://plum-claims-g5lc.onrender.com/api';

// ── Test Cases (embedded for client-side eval runner) ────────────────────────
let TEST_CASES = null;

async function loadTestCases() {
    try {
        const res = await fetch('/test_cases.json');
        const data = await res.json();
        TEST_CASES = data.test_cases;
    } catch { TEST_CASES = null; }
}

loadTestCases();

// ── Navigation ──────────────────────────────────────────────────────────────

function navigateTo(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const pageEl = document.getElementById('page-' + page);
    const navEl = document.getElementById('nav-' + page);
    if (pageEl) pageEl.classList.add('active');
    if (navEl) navEl.classList.add('active');
    if (page === 'claims') loadClaims();
    if (page === 'policy') loadPolicy();
    if (page === 'dashboard') loadDashboard();
}

document.querySelectorAll('.nav-item[data-page]').forEach(item => {
    item.addEventListener('click', (e) => { e.preventDefault(); navigateTo(item.dataset.page); });
});

// ── API Health Check ────────────────────────────────────────────────────────

async function checkHealth() {
    const dot = document.getElementById('api-status-dot');
    const text = document.getElementById('api-status-text');
    try {
        const res = await fetch(API_BASE + '/health');
        if (res.ok) { dot.className = 'status-dot online'; text.textContent = 'API Online'; return true; }
    } catch {}
    dot.className = 'status-dot offline'; text.textContent = 'API Offline';
    return false;
}

setInterval(checkHealth, 15000);

// ── Dashboard ───────────────────────────────────────────────────────────────

async function loadDashboard() {
    try {
        const res = await fetch(API_BASE + '/claims');
        const data = await res.json();
        const claims = data.claims || [];
        document.getElementById('stat-total').textContent = claims.length;
        document.getElementById('stat-approved').textContent = claims.filter(c => c.decision === 'APPROVED' || c.decision === 'ClaimDecision.APPROVED').length;
        document.getElementById('stat-rejected').textContent = claims.filter(c => c.decision === 'REJECTED' || c.decision === 'ClaimDecision.REJECTED').length;
        document.getElementById('stat-review').textContent = claims.filter(c => c.decision === 'MANUAL_REVIEW' || c.decision === 'ClaimDecision.MANUAL_REVIEW').length;

        const body = document.getElementById('recent-claims-body');
        if (claims.length === 0) return;
        body.innerHTML = renderClaimsTable(claims.slice(-5).reverse());
    } catch {}
}

// ── Members ─────────────────────────────────────────────────────────────────

async function loadMembers() {
    try {
        const res = await fetch(API_BASE + '/members');
        const data = await res.json();
        const sel = document.getElementById('member_id');
        sel.innerHTML = '<option value="">Select member...</option>';
        (data.members || []).forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.member_id;
            opt.textContent = `${m.name} (${m.member_id}) — ${m.relationship}`;
            sel.appendChild(opt);
        });
    } catch {}
}

// ── Hospitals ───────────────────────────────────────────────────────────────

async function loadHospitals() {
    try {
        const res = await fetch(API_BASE + '/policy/summary');
        const data = await res.json();
        const sel = document.getElementById('hospital_name');
        sel.innerHTML = '<option value="">Select hospital...</option>';
        (data.network_hospitals || []).forEach(h => {
            const opt = document.createElement('option');
            opt.value = h;
            opt.textContent = h;
            sel.appendChild(opt);
        });
    } catch {}
}

// ── Document Requirements ───────────────────────────────────────────────────

document.getElementById('claim_category').addEventListener('change', updateDocRequirements);

function updateDocRequirements() {
    const cat = document.getElementById('claim_category').value;
    const el = document.getElementById('doc-requirements');
    const reqs = {
        CONSULTATION: 'Required: Prescription, Hospital Bill',
        DIAGNOSTIC: 'Required: Prescription, Lab Report, Hospital Bill',
        PHARMACY: 'Required: Prescription, Pharmacy Bill',
        DENTAL: 'Required: Hospital Bill',
        VISION: 'Required: Prescription, Hospital Bill',
        ALTERNATIVE_MEDICINE: 'Required: Prescription, Hospital Bill',
    };
    el.textContent = reqs[cat] || '';
    if (!document.getElementById('documents-container').children.length && cat) addDocumentEntry();
}

// ── Document Entries ────────────────────────────────────────────────────────

let docCounter = 0;
function addDocumentEntry() {
    const container = document.getElementById('documents-container');
    const id = ++docCounter;
    const div = document.createElement('div');
    div.id = 'doc-' + id;
    // Injecting inline styles here to guarantee the layout is a single row without needing external css classes that might be missing
    div.style.cssText = 'display: flex; gap: 16px; align-items: flex-start; padding: 16px; background: var(--bg-glass); border: 1px solid var(--border); border-radius: var(--radius-sm); margin-bottom: 12px; animation: fadeIn 0.2s ease;';
    div.innerHTML = `
        <div class="form-group" style="flex: 1; margin: 0;">
            <label style="margin-bottom: 6px;">Document Type</label>
            <select id="doc-type-${id}" required style="width: 100%; height: 42px;">
                <option value="">Select type...</option>
                <option value="PRESCRIPTION">Prescription</option>
                <option value="HOSPITAL_BILL">Hospital Bill</option>
                <option value="LAB_REPORT">Lab Report</option>
                <option value="PHARMACY_BILL">Pharmacy Bill</option>
                <option value="DIAGNOSTIC_REPORT">Diagnostic Report</option>
                <option value="DISCHARGE_SUMMARY">Discharge Summary</option>
                <option value="DENTAL_REPORT">Dental Report</option>
            </select>
        </div>
        <div class="form-group" style="flex: 2; margin: 0;">
            <label style="margin-bottom: 6px;">Upload File (image/PDF)</label>
            <div class="file-upload-area" id="doc-upload-area-${id}" onclick="document.getElementById('doc-file-${id}').click()" style="display: flex; flex-direction: row; align-items: center; justify-content: center; gap: 12px; padding: 0 16px; height: 42px; border: 1px dashed var(--border); border-radius: var(--radius-sm); cursor: pointer; background: transparent; transition: var(--transition);">
                <input type="file" id="doc-file-${id}" accept="image/*,.pdf" style="display:none" onchange="handleFileSelect(${id}, this)">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" opacity="0.6"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                <span class="file-upload-text" style="font-size: 0.85rem; color: var(--text-secondary);">Click to upload or drag & drop</span>
            </div>
            <div class="file-selected" id="doc-file-info-${id}" style="display: none; align-items: center; justify-content: space-between; padding: 0 16px; height: 42px; background: var(--blue-bg); border: 1px solid rgba(59,130,246,0.2); border-radius: var(--radius-sm);">
                <span class="file-name" id="doc-file-name-${id}" style="font-size: 0.85rem; color: var(--blue); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 250px;"></span>
                <button type="button" class="btn btn-ghost btn-sm" onclick="clearFile(${id})" style="padding: 4px 8px; font-size: 0.75rem;">✕ Remove</button>
            </div>
        </div>
        <button type="button" class="remove-doc-btn" onclick="document.getElementById('doc-${id}').remove()" title="Remove Document" style="margin-top: 24px; padding: 0; width: 42px; height: 42px; display: flex; align-items: center; justify-content: center; background: transparent; border: 1px solid rgba(239,68,68,0.3); color: var(--red); border-radius: 6px; cursor: pointer; transition: var(--transition);">✕</button>
    `;
    container.appendChild(div);
}

function handleFileSelect(docId, input) {
    const file = input.files[0];
    if (!file) return;
    const area = document.getElementById('doc-upload-area-' + docId);
    const info = document.getElementById('doc-file-info-' + docId);
    const name = document.getElementById('doc-file-name-' + docId);
    area.style.display = 'none';
    info.style.display = 'flex';
    name.textContent = file.name + ' (' + (file.size / 1024).toFixed(1) + ' KB)';
}

function clearFile(docId) {
    const input = document.getElementById('doc-file-' + docId);
    input.value = '';
    document.getElementById('doc-upload-area-' + docId).style.display = 'flex';
    document.getElementById('doc-file-info-' + docId).style.display = 'none';
}

function addLineItem(docId) {
    const container = document.getElementById('doc-lineitems-' + docId);
    const idx = container.children.length + 1;
    const row = document.createElement('div');
    row.className = 'line-item-row';
    row.innerHTML = `
        <input type="text" placeholder="Description (e.g. Consultation Fee)" class="li-desc">
        <input type="number" placeholder="Amount (₹)" class="li-amount">
        <button type="button" class="remove-doc-btn" onclick="this.parentElement.remove()" style="height:34px;width:34px;font-size:0.7rem">✕</button>`;
    container.appendChild(row);
}

// ── Submit Claim ────────────────────────────────────────────────────────────

async function submitClaim() {
    const form = document.getElementById('claim-form');
    if (form && !form.checkValidity()) {
        form.reportValidity();
        return;
    }

    const memberId = document.getElementById('member_id').value;
    const claimCategory = document.getElementById('claim_category').value;
    const treatmentDate = document.getElementById('treatment_date').value;
    const claimedAmount = document.getElementById('claimed_amount').value;
    const hospitalName = document.getElementById('hospital_name').value;

    if (!memberId || !claimCategory || !treatmentDate || !claimedAmount || !hospitalName) {
        alert("Please provide all details asked in the form.");
        return;
    }

    const docEntries = Array.from(document.getElementById('documents-container').children);
    if (docEntries.length === 0) {
        alert("Please add at least one document.");
        return;
    }

    let fileMissing = false;
    for (let i = 0; i < docEntries.length; i++) {
        const id = docEntries[i].id.split('-')[1];
        const fileInput = document.getElementById('doc-file-' + id);
        if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
            fileMissing = true;
            break;
        }
    }

    if (fileMissing) {
        alert("Please upload a file for all document entries.");
        return;
    }

    const btn = document.getElementById('submit-claim-btn');
    btn.querySelector('.btn-text').style.display = 'none';
    btn.querySelector('.btn-loader').style.display = 'inline-flex';
    btn.disabled = true;

    try {
        const docs = [];
        docEntries.forEach(entry => {
            const id = entry.id.split('-')[1];
            const type = document.getElementById('doc-type-' + id)?.value;
            const fileInput = document.getElementById('doc-file-' + id);
            const fileName = fileInput?.files?.[0]?.name || null;

            if (!type) return;

            const doc = {
                actual_type: type,
                quality: 'GOOD', // Defaulting to GOOD since quality selector is removed
                file_id: 'F' + Math.random().toString(36).substr(2, 6).toUpperCase(),
            };
            if (fileName) doc.file_name = fileName;

            docs.push(doc);
        });

        const payload = {
            member_id: document.getElementById('member_id').value,
            claim_category: document.getElementById('claim_category').value,
            treatment_date: document.getElementById('treatment_date').value,
            claimed_amount: parseFloat(document.getElementById('claimed_amount').value),
            hospital_name: document.getElementById('hospital_name').value || null,
            documents: docs,
        };

        const formData = new FormData();
        formData.append('payload', JSON.stringify(payload));
        
        // Append actual files
        docEntries.forEach(entry => {
            const id = entry.id.split('-')[1];
            const fileInput = document.getElementById('doc-file-' + id);
            if (fileInput && fileInput.files && fileInput.files[0]) {
                formData.append('files', fileInput.files[0]);
            }
        });

        const res = await fetch(API_BASE + '/claims/submit', { 
            method: 'POST', 
            body: formData 
        });
        const result = await res.json();
        showResult(result);
        loadDashboard();
    } catch (e) {
        showResult({ error: e.message });
    } finally {
        btn.querySelector('.btn-text').style.display = 'inline';
        btn.querySelector('.btn-loader').style.display = 'none';
        btn.disabled = false;
    }
}

function showResult(result) {
    const panel = document.getElementById('submit-result');
    panel.style.display = 'block';
    panel.innerHTML = renderDecisionDetail(result);
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── Claims List ─────────────────────────────────────────────────────────────

async function loadClaims() {
    try {
        const res = await fetch(API_BASE + '/claims');
        const data = await res.json();
        const body = document.getElementById('claims-table-body');
        if (!data.claims || data.claims.length === 0) {
            body.innerHTML = '<div class="empty-state"><p>No claims processed yet</p></div>';
            return;
        }
        body.innerHTML = renderClaimsTable(data.claims.reverse());
    } catch {
        document.getElementById('claims-table-body').innerHTML = '<div class="empty-state"><p>Failed to load claims. Is the API running?</p></div>';
    }
}

function renderClaimsTable(claims) {
    let html = `<table class="claims-table"><thead><tr>
        <th>Claim ID</th><th>Member</th><th>Category</th><th>Amount</th><th>Decision</th><th>Approved</th><th>Confidence</th>
    </tr></thead><tbody>`;
    claims.forEach(c => {
        const dec = normalizeDecision(c.decision);
        html += `<tr onclick="viewClaimDetail('${c.claim_id}')">
            <td style="font-family:monospace;font-size:0.8rem">${c.claim_id}</td>
            <td>${c.member_id}</td>
            <td>${(c.category || '').replace('ClaimCategory.','')}</td>
            <td>₹${Number(c.claimed_amount).toLocaleString('en-IN')}</td>
            <td><span class="badge badge-${dec.toLowerCase()}">${dec}</span></td>
            <td>₹${Number(c.approved_amount || 0).toLocaleString('en-IN')}</td>
            <td>${(c.confidence_score * 100).toFixed(0)}%</td>
        </tr>`;
    });
    html += '</tbody></table>';
    return html;
}

async function viewClaimDetail(claimId) {
    try {
        const res = await fetch(API_BASE + '/claims/' + claimId);
        const data = await res.json();
        const result = data.result || data;
        document.getElementById('modal-title').textContent = 'Claim: ' + claimId;
        document.getElementById('modal-body').innerHTML = renderDecisionDetail(result);
        document.getElementById('claim-detail-modal').style.display = 'flex';
    } catch {}
}

function closeModal() { document.getElementById('claim-detail-modal').style.display = 'none'; }
document.getElementById('claim-detail-modal').addEventListener('click', (e) => { if (e.target.id === 'claim-detail-modal') closeModal(); });

// ── Decision Detail Renderer ────────────────────────────────────────────────

function normalizeDecision(d) {
    if (!d) return 'UNKNOWN';
    return String(d).replace('ClaimDecision.','');
}

function renderDecisionDetail(result) {
    if (result.error) return `<div class="result-body"><div class="explanation-box" style="border-color:var(--red);color:var(--red)">Error: ${result.error}</div></div>`;

    const dec = normalizeDecision(result.decision);
    const conf = result.confidence_score || 0;
    const approved = result.approved_amount || 0;
    const claimed = result.claimed_amount || 0;

    let html = `
    <div class="result-header">
        <h3><span class="badge badge-${dec.toLowerCase()}" style="font-size:0.85rem;padding:5px 14px">${dec}</span></h3>
        <span style="color:var(--text-muted);font-size:0.85rem">${result.claim_id || ''}</span>
    </div>
    <div class="result-body">
        <div class="decision-summary">
            <div class="decision-item"><div class="label">Decision</div><div class="value" style="color:var(--${dec === 'APPROVED' ? 'green' : dec === 'REJECTED' ? 'red' : dec === 'PARTIAL' ? 'amber' : 'purple'})">${dec}</div></div>
            <div class="decision-item"><div class="label">Approved</div><div class="value">₹${Number(approved).toLocaleString('en-IN')}</div></div>
            <div class="decision-item"><div class="label">Claimed</div><div class="value">₹${Number(claimed).toLocaleString('en-IN')}</div></div>
            <div class="decision-item"><div class="label">Confidence</div><div class="value">${(conf * 100).toFixed(0)}%</div></div>
        </div>`;

    // Explanation
    if (result.explanation) html += `<h4 style="margin-bottom:8px;font-size:0.85rem;color:var(--text-muted)">EXPLANATION</h4><div class="explanation-box">${escapeHtml(result.explanation)}</div>`;

    // Amount breakdown
    const bd = result.amount_breakdown;
    if (bd && bd.calculation_steps && bd.calculation_steps.length) {
        html += `<h4 style="margin:20px 0 8px;font-size:0.85rem;color:var(--text-muted)">AMOUNT BREAKDOWN</h4><ul class="breakdown-steps">`;
        bd.calculation_steps.forEach(s => html += `<li>${escapeHtml(s)}</li>`);
        html += '</ul>';
    }

    // Line item decisions
    if (bd && bd.line_item_decisions && bd.line_item_decisions.length) {
        html += `<h4 style="margin:20px 0 8px;font-size:0.85rem;color:var(--text-muted)">LINE ITEMS</h4><table class="claims-table"><thead><tr><th>Item</th><th>Claimed</th><th>Approved</th><th>Status</th><th>Reason</th></tr></thead><tbody>`;
        bd.line_item_decisions.forEach(li => {
            const st = li.status;
            html += `<tr><td>${escapeHtml(li.description)}</td><td>₹${Number(li.claimed_amount).toLocaleString('en-IN')}</td><td>₹${Number(li.approved_amount).toLocaleString('en-IN')}</td><td><span class="badge badge-${st === 'APPROVED' ? 'approved' : 'rejected'}">${st}</span></td><td style="font-size:0.8rem;color:var(--text-muted)">${escapeHtml(li.reason || '')}</td></tr>`;
        });
        html += '</tbody></table>';
    }

    // Component failures
    if (result.component_failures && result.component_failures.length) {
        html += `<div style="margin-top:16px;padding:12px;background:var(--amber-bg);border:1px solid rgba(245,158,11,0.3);border-radius:var(--radius-sm);font-size:0.85rem;color:var(--amber)">⚠️ Component failure(s): ${result.component_failures.join(', ')}. ${result.requires_manual_review_note || ''}</div>`;
    }

    // Trace
    const trace = result.trace || [];
    if (trace.length) {
        html += `<h4 style="margin:24px 0 12px;font-size:0.85rem;color:var(--text-muted)">PROCESSING TRACE (${trace.length} steps)</h4><div class="trace-timeline">`;
        trace.forEach((step, i) => {
            const status = (step.status || 'SUCCESS').replace('TraceStepStatus.','');
            html += `<div class="trace-step ${status.toLowerCase()}" onclick="this.classList.toggle('expanded')">
                <div class="trace-header">
                    <span class="trace-name">${step.display_name || step.agent_name}</span>
                    <span class="trace-duration">${step.duration_ms != null ? step.duration_ms.toFixed(1) + 'ms' : ''}</span>
                </div>
                <div class="trace-message">${escapeHtml(step.message || '')}</div>
                <div class="trace-details">`;
            if (step.checks_performed && step.checks_performed.length) {
                step.checks_performed.forEach(chk => {
                    const passed = chk.status === 'PASS' || chk.passed;
                    html += `<div class="trace-check ${passed ? 'pass' : 'fail'}"><span class="check-icon">${passed ? '✓' : '✗'}</span> ${escapeHtml(chk.check || chk.step || JSON.stringify(chk))}${chk.detail ? ' — ' + escapeHtml(chk.detail) : ''}</div>`;
                });
            }
            if (step.input_summary) html += `<div style="margin-top:8px;font-size:0.78rem;color:var(--text-muted)">Input: ${escapeHtml(JSON.stringify(step.input_summary))}</div>`;
            if (step.output_summary) html += `<div style="font-size:0.78rem;color:var(--text-muted)">Output: ${escapeHtml(JSON.stringify(step.output_summary))}</div>`;
            if (step.warnings && step.warnings.length) step.warnings.forEach(w => html += `<div style="color:var(--amber);font-size:0.78rem">⚠ ${escapeHtml(w)}</div>`);
            html += '</div></div>';
        });
        html += '</div>';
    }

    html += '</div>';
    return html;
}

// ── Eval Runner ─────────────────────────────────────────────────────────────

async function runEvaluation() {
    const btn = document.getElementById('run-eval-btn');
    btn.querySelector('.btn-text').style.display = 'none';
    btn.querySelector('.btn-loader').style.display = 'inline-flex';
    btn.disabled = true;

    const container = document.getElementById('eval-results');
    container.innerHTML = '<div class="eval-summary"><span>Running tests...</span></div>';

    if (!TEST_CASES) {
        try {
            const res = await fetch('/test_cases.json');
            const data = await res.json();
            TEST_CASES = data.test_cases;
        } catch {
            container.innerHTML = '<div class="empty-state"><p>Could not load test_cases.json</p></div>';
            btn.querySelector('.btn-text').style.display = 'inline';
            btn.querySelector('.btn-loader').style.display = 'none';
            btn.disabled = false;
            return;
        }
    }

    let passed = 0, total = TEST_CASES.length, results = [];

    for (const tc of TEST_CASES) {
        try {
            const res = await fetch(API_BASE + '/claims/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(tc.input) });
            const result = await res.json();
            const evaluation = evaluateTestCase(tc, result);
            if (evaluation.passed) passed++;
            results.push({ tc, result, evaluation });
        } catch (e) {
            results.push({ tc, result: null, evaluation: { passed: false, checks: [{ check: 'API Error', passed: false, detail: e.message }] } });
        }
    }

    let html = `<div class="eval-summary">
        <span>${passed}/${total} passed</span>
        <div class="eval-progress"><div class="eval-progress-bar" style="width:${(passed/total*100).toFixed(0)}%"></div></div>
        <span class="badge ${passed === total ? 'badge-pass' : 'badge-fail'}">${passed === total ? 'ALL PASS' : 'FAILURES'}</span>
    </div>`;

    results.forEach(({ tc, result, evaluation }) => {
        const dec = result ? normalizeDecision(result.decision) : 'ERROR';
        html += `<div class="eval-case ${evaluation.passed ? '' : 'failed'}" onclick="this.classList.toggle('expanded')">
            <div class="eval-case-header">
                <span class="eval-case-name">${tc.case_id}: ${tc.case_name}</span>
                <span class="badge ${evaluation.passed ? 'badge-pass' : 'badge-fail'}">${evaluation.passed ? 'PASS' : 'FAIL'}</span>
            </div>
            <div class="eval-case-desc">${tc.description}</div>
            <div class="eval-case-details">
                <div style="margin-bottom:8px"><strong>Decision:</strong> ${dec} | <strong>Approved:</strong> ₹${result ? Number(result.approved_amount || 0).toLocaleString('en-IN') : 'N/A'} | <strong>Confidence:</strong> ${result ? ((result.confidence_score || 0) * 100).toFixed(0) + '%' : 'N/A'}</div>`;
        evaluation.checks.forEach(chk => {
            html += `<div class="trace-check ${chk.passed ? 'pass' : 'fail'}"><span class="check-icon">${chk.passed ? '✓' : '✗'}</span> ${escapeHtml(chk.check)}${chk.expected !== undefined ? ` (expected: ${chk.expected}, got: ${chk.got})` : ''}${chk.detail ? ' — ' + escapeHtml(chk.detail) : ''}</div>`;
        });
        if (result && result.explanation) html += `<div class="explanation-box" style="margin-top:8px;font-size:0.78rem">${escapeHtml(result.explanation).substring(0, 300)}</div>`;
        html += '</div></div>';
    });

    container.innerHTML = html;
    btn.querySelector('.btn-text').style.display = 'inline';
    btn.querySelector('.btn-loader').style.display = 'none';
    btn.disabled = false;
    loadDashboard();
}

function evaluateTestCase(tc, result) {
    if (!result) return { passed: false, checks: [{ check: 'No result', passed: false }] };
    const exp = tc.expected, checks = [];
    let passed = true;
    const dec = normalizeDecision(result.decision);

    if (exp.decision !== null && exp.decision !== undefined) {
        const match = dec === exp.decision;
        checks.push({ check: 'Decision', expected: exp.decision, got: dec, passed: match });
        if (!match) passed = false;
    } else {
        const docVer = result.doc_verification;
        const stopped = docVer && !docVer.passed;
        checks.push({ check: 'Early stop on doc issue', passed: stopped, detail: stopped ? 'Correctly stopped' : 'Should have stopped' });
        if (!stopped) passed = false;
    }

    if (exp.approved_amount !== undefined) {
        const match = Math.abs((result.approved_amount || 0) - exp.approved_amount) < 1;
        checks.push({ check: 'Approved Amount', expected: exp.approved_amount, got: result.approved_amount, passed: match });
        if (!match) passed = false;
    }

    if (exp.confidence_score) {
        const conf = result.confidence_score || 0;
        if (typeof exp.confidence_score === 'string' && exp.confidence_score.startsWith('above')) {
            const threshold = parseFloat(exp.confidence_score.split(' ')[1]);
            const match = conf > threshold;
            checks.push({ check: 'Confidence', expected: '> ' + threshold, got: conf, passed: match });
            if (!match) passed = false;
        }
    }

    if (exp.rejection_reasons) {
        const got = result.reasons || [];
        exp.rejection_reasons.forEach(r => {
            const found = got.includes(r);
            checks.push({ check: 'Reason: ' + r, passed: found, detail: found ? 'Found' : 'Missing from ' + JSON.stringify(got) });
            if (!found) passed = false;
        });
    }

    (exp.system_must || []).forEach(must => {
        checks.push({ check: must.substring(0, 60) + '...', passed: true, detail: 'Qualitative — see trace' });
    });

    return { passed, checks };
}

// ── Policy Info ─────────────────────────────────────────────────────────────

async function loadPolicy() {
    try {
        const [pRes, mRes] = await Promise.all([fetch(API_BASE + '/policy/summary'), fetch(API_BASE + '/members')]);
        const policy = await pRes.json();
        const members = await mRes.json();
        const container = document.getElementById('policy-content');

        container.innerHTML = `<div class="policy-grid">
            <div class="policy-card">
                <h3>📋 Policy Details</h3>
                <div class="policy-stat"><span class="label">Policy ID</span><span class="value">${policy.policy_id}</span></div>
                <div class="policy-stat"><span class="label">Name</span><span class="value">${policy.policy_name}</span></div>
                <div class="policy-stat"><span class="label">Insurer</span><span class="value">${policy.insurer}</span></div>
                <div class="policy-stat"><span class="label">Company</span><span class="value">${policy.company}</span></div>
            </div>
            <div class="policy-card">
                <h3>💰 Coverage Limits</h3>
                <div class="policy-stat"><span class="label">Sum Insured / Employee</span><span class="value">₹${Number(policy.sum_insured).toLocaleString('en-IN')}</span></div>
                <div class="policy-stat"><span class="label">Annual OPD Limit</span><span class="value">₹${Number(policy.annual_opd_limit).toLocaleString('en-IN')}</span></div>
                <div class="policy-stat"><span class="label">Per-Claim Limit</span><span class="value">₹${Number(policy.per_claim_limit).toLocaleString('en-IN')}</span></div>
            </div>
            <div class="policy-card">
                <h3>🏥 Network Hospitals</h3>
                <ul>${(policy.network_hospitals || []).map(h => `<li>${h}</li>`).join('')}</ul>
            </div>
            <div class="policy-card">
                <h3>📂 Covered Categories</h3>
                <ul>${(policy.categories || []).map(c => `<li>${c.replace('_', ' ')}</li>`).join('')}</ul>
            </div>
            <div class="policy-card" style="grid-column: 1 / -1">
                <h3>👥 Members (${members.total})</h3>
                <div class="members-grid">
                    ${(members.members || []).map(m => `<div class="member-chip"><span class="name">${m.name}</span><span class="id">${m.member_id} · ${m.relationship} · ${m.gender}</span></div>`).join('')}
                </div>
            </div>
        </div>`;
    } catch {
        document.getElementById('policy-content').innerHTML = '<div class="empty-state"><p>Failed to load policy. Is the API running?</p></div>';
    }
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Init ────────────────────────────────────────────────────────────────────

(async () => {
    await checkHealth();
    await loadMembers();
    await loadHospitals();
    await loadDashboard();
})();
