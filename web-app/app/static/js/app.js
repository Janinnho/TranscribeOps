// Sidebar toggle for mobile
document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebarBackdrop');

    if (toggle && sidebar) {
        function closeSidebar() {
            sidebar.classList.remove('show');
            if (backdrop) backdrop.classList.remove('show');
        }

        toggle.addEventListener('click', (e) => {
            e.stopPropagation();
            sidebar.classList.toggle('show');
            if (backdrop) backdrop.classList.toggle('show');
        });

        if (backdrop) {
            backdrop.addEventListener('click', closeSidebar);
        }

        document.addEventListener('click', (e) => {
            if (sidebar.classList.contains('show') &&
                !sidebar.contains(e.target) &&
                e.target !== toggle &&
                !toggle.contains(e.target)) {
                closeSidebar();
            }
        });
    }
});

// Track previous job states for auto-display on completion
let _prevJobStates = {};

// File upload initialization
function initUpload(formId, fileInputId, dropZoneId, selectedFileId, fileNameId, fileSizeId,
                    removeFileId, uploadBtnId, progressId, jobType) {
    const form = document.getElementById(formId);
    const fileInput = document.getElementById(fileInputId);
    const dropZone = document.getElementById(dropZoneId);
    const selectedFile = document.getElementById(selectedFileId);
    const fileName = document.getElementById(fileNameId);
    const fileSize = document.getElementById(fileSizeId);
    const removeFile = document.getElementById(removeFileId);
    const uploadBtn = document.getElementById(uploadBtnId);
    const progress = document.getElementById(progressId);

    if (!form || !fileInput || !dropZone) return;

    dropZone.addEventListener('click', () => fileInput.click());

    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            fileInput.files = e.dataTransfer.files;
            showSelectedFile();
        }
    });

    fileInput.addEventListener('change', showSelectedFile);

    function checkFileSize(file) {
        if (typeof getSelectedModelMaxSize === 'function') {
            const maxMb = getSelectedModelMaxSize();
            if (maxMb > 0 && file.size > maxMb * 1024 * 1024) {
                alert(window.tr('File too large. Maximum upload size for this model: {max} MB. Your file: {size} MB', {max: maxMb, size: (file.size / 1024 / 1024).toFixed(1)}));
                return false;
            }
        }
        return true;
    }

    function showSelectedFile() {
        if (fileInput.files.length) {
            const f = fileInput.files[0];
            if (!checkFileSize(f)) {
                fileInput.value = '';
                return;
            }
            fileName.textContent = f.name;
            fileSize.textContent = formatSize(f.size);
            selectedFile.classList.remove('d-none');
            dropZone.classList.add('d-none');
            uploadBtn.disabled = false;
        }
    }

    removeFile.addEventListener('click', () => {
        fileInput.value = '';
        selectedFile.classList.add('d-none');
        dropZone.classList.remove('d-none');
        uploadBtn.disabled = true;
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (!fileInput.files.length) return;

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('job_type', jobType);
        const speechModel = document.getElementById('speechModel');
        if (speechModel) formData.append('speech_model_id', speechModel.value);
        const language = document.getElementById('language');
        if (language) formData.append('language', language.value);
        const multiSpeaker = document.getElementById('multiSpeaker');
        if (multiSpeaker) formData.append('multi_speaker', multiSpeaker.value);
        const saveAudio = document.getElementById('saveAudio');
        if (saveAudio) formData.append('save_audio', saveAudio.checked ? '1' : '0');

        uploadBtn.disabled = true;
        progress.classList.remove('d-none');
        const bar = progress.querySelector('.progress-bar');

        const token = document.querySelector('meta[name="csrf-token"]').content;

        const xhr = new XMLHttpRequest();
        xhr.upload.addEventListener('progress', (ev) => {
            if (ev.lengthComputable) {
                const pct = Math.round((ev.loaded / ev.total) * 100);
                bar.style.width = pct + '%';
            }
        });

        xhr.addEventListener('load', () => {
            progress.classList.add('d-none');
            bar.style.width = '0%';
            fileInput.value = '';
            selectedFile.classList.add('d-none');
            dropZone.classList.remove('d-none');
            uploadBtn.disabled = true;
            if (_currentListUrl) loadJobs(_currentListUrl, _currentDeleteBase, _currentDetailBase);
            else if (typeof loadJobs === 'function') loadJobs('/api/jobs/' + jobType, '/api/job', '/transcription-job');
        });

        xhr.addEventListener('error', () => {
            progress.classList.add('d-none');
            uploadBtn.disabled = false;
            alert(window.tr('Upload failed.'));
        });

        xhr.open('POST', '/api/upload');
        xhr.setRequestHeader('X-CSRFToken', token);
        xhr.send(formData);
    });
}

// Track current API URLs for reload after upload
let _currentListUrl = null;
let _currentDeleteBase = null;
let _currentDetailBase = null;
let _currentJobs = [];

// Load jobs from API - accepts list URL, delete base URL, and detail page base URL
async function loadJobs(listUrl, deleteUrlBase, detailBase) {
    _currentListUrl = listUrl;
    _currentDeleteBase = deleteUrlBase;
    if (detailBase) _currentDetailBase = detailBase;
    const container = document.getElementById('jobList');
    if (!container) return;

    try {
        const resp = await fetch(listUrl);
        const jobs = await resp.json();
        _currentJobs = jobs;
        updateEtaData(jobs);

        if (!jobs.length) {
            _prevJobStates = {};
        }

        // Detect newly completed jobs and navigate to detail page
        for (const job of jobs) {
            const prevStatus = _prevJobStates[job.id];
            if (prevStatus && prevStatus !== 'completed' && job.status === 'completed') {
                window.location.href = (_currentDetailBase || '/job') + '/' + job.id;
                return;
            }
            _prevJobStates[job.id] = job.status;
        }

        // Apply current search filter
        const searchInput = document.getElementById('jobSearchInput');
        const filterText = searchInput ? searchInput.value.trim().toLowerCase() : '';
        renderJobList(filterText);
    } catch (err) {
        console.error('Failed to load jobs:', err);
    }
}

function renderJobList(filterText) {
    const container = document.getElementById('jobList');
    if (!container) return;

    let jobs = _currentJobs;
    if (filterText) {
        jobs = jobs.filter(job =>
            (job.title || '').toLowerCase().includes(filterText) ||
            (job.created_at || '').includes(filterText)
        );
    }

    if (!jobs.length) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="bi bi-${filterText ? 'search' : 'inbox'} display-6"></i>
                <p class="mt-2">${filterText ? window.tr('No matches') : window.tr('No entries yet.')}</p>
            </div>`;
        return;
    }

    const dBase = _currentDetailBase || '/job';
    const listUrl = _currentListUrl;
    const deleteUrlBase = _currentDeleteBase;
    container.innerHTML = jobs.map(job => `
        <div class="job-item ${job.id === (typeof currentJobId !== 'undefined' ? currentJobId : null) ? 'active' : ''}" onclick="selectJob('${job.id}', '${dBase}')">
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1">
                    <div class="fw-medium text-truncate" style="max-width: 250px;">${escapeHtml(job.title || window.tr('Job'))}</div>
                    <small class="text-muted">${job.created_at}</small>
                </div>
                <div class="d-flex align-items-center gap-2">
                    ${statusBadge(job.status)}
                    <button class="btn btn-sm btn-link text-danger p-0" onclick="event.stopPropagation(); deleteItem('${job.id}', '${listUrl}', '${deleteUrlBase}')" title="${window.tr('Delete')}">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </div>
            ${job.status === 'processing' ? '<div class="mt-2"><div class="progress" style="height:3px"><div class="progress-bar progress-bar-striped progress-bar-animated bg-info" style="width:100%"></div></div></div>' : ''}
            ${job.status === 'failed' ? `<small class="text-danger d-block mt-1">${escapeHtml(job.error_message || window.tr('Error'))}</small>` : ''}
            ${(job.status === 'processing' || job.status === 'pending') && job.eta_seconds != null ? `<small class="text-muted d-block mt-1" data-eta-job="${job.id}"></small>` : ''}
        </div>
    `).join('');
    tickEtaCountdowns();
}

// Initialize job search input
function initJobSearch() {
    const input = document.getElementById('jobSearchInput');
    if (!input) return;
    input.addEventListener('input', () => {
        renderJobList(input.value.trim().toLowerCase());
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initJobSearch();
});

function selectJob(jobId, detailBase) {
    window.location.href = (detailBase || '/job') + '/' + jobId;
}

async function deleteItem(itemId, listUrl, deleteUrlBase) {
    if (!confirm(window.tr('Really delete this entry?'))) return;
    const token = document.querySelector('meta[name="csrf-token"]').content;
    await fetch(`${deleteUrlBase}/${itemId}`, {
        method: 'DELETE',
        headers: {'X-CSRFToken': token}
    });
    loadJobs(listUrl, deleteUrlBase);
}

function statusBadge(status) {
    const map = {
        'pending': `<span class="badge bg-warning text-dark"><i class="bi bi-hourglass-split me-1"></i>${window.tr('Pending')}</span>`,
        'processing': `<span class="badge bg-info"><span class="spinner-grow spinner-grow-sm me-1"></span>${window.tr('Processing')}</span>`,
        'completed': `<span class="badge bg-success"><i class="bi bi-check-circle me-1"></i>${window.tr('Completed')}</span>`,
        'failed': `<span class="badge bg-danger"><i class="bi bi-x-circle me-1"></i>${window.tr('Failed')}</span>`
    };
    return map[status] || `<span class="badge bg-secondary">${status}</span>`;
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// --- ETA countdown ---
// Stores { jobId: { etaSeconds, fetchedAt, startedAt, estimatedTotal, status } }
let _etaData = {};
let _etaInterval = null;

function formatEtaTime(secs) {
    if (secs == null || secs < 0) return '';
    secs = Math.max(0, Math.round(secs));
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return m > 0 ? window.tr('{m} min {s} sec', {m: m, s: s}) : window.tr('{s} sec', {s: s});
}

function updateEtaData(jobs) {
    const now = Date.now() / 1000;
    for (const job of jobs) {
        if (job.status === 'processing' && job.processing_started_at && job.estimated_total_secs != null) {
            // For processing jobs: store start time + total estimate for client-side calculation
            _etaData[job.id] = {
                startedAt: new Date(job.processing_started_at).getTime() / 1000,
                estimatedTotal: job.estimated_total_secs,
                status: 'processing',
            };
        } else if (job.status === 'pending' && job.eta_seconds != null) {
            // For pending jobs: use server-provided eta_seconds with fetchedAt countdown
            const existing = _etaData[job.id];
            if (!existing || existing.status !== 'pending') {
                _etaData[job.id] = {
                    etaSeconds: job.eta_seconds,
                    fetchedAt: now,
                    status: 'pending',
                };
            }
        } else {
            delete _etaData[job.id];
        }
    }
    if (!_etaInterval) {
        _etaInterval = setInterval(tickEtaCountdowns, 1000);
    }
}

function getEtaRemaining(jobId) {
    const d = _etaData[jobId];
    if (!d) return null;
    if (d.status === 'processing') {
        // Compute remaining from processing start time + estimated total
        const elapsed = Date.now() / 1000 - d.startedAt;
        return Math.max(0, Math.round(d.estimatedTotal - elapsed));
    }
    // Pending: countdown from server-provided eta_seconds
    const elapsed = Date.now() / 1000 - d.fetchedAt;
    return Math.max(0, Math.round(d.etaSeconds - elapsed));
}

function tickEtaCountdowns() {
    // Update all visible ETA elements
    document.querySelectorAll('[data-eta-job]').forEach(el => {
        const jobId = el.getAttribute('data-eta-job');
        const remaining = getEtaRemaining(jobId);
        if (remaining != null && remaining >= 0) {
            const d = _etaData[jobId];
            const prefix = d && d.status === 'pending' ? window.tr('Estimated wait time: ') : window.tr('Remaining time: ');
            el.textContent = prefix + formatEtaTime(remaining);
        } else {
            el.textContent = '';
        }
    });
}
