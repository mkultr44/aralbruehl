const STATUS_SEQUENCE = ['pending', 'arrived', 'done'];
const STATUS_LABELS = {
  pending: 'Auto nicht da',
  arrived: 'Auto da',
  done: 'Auto fertig',
};

const CATEGORY_CONFIG = {
  routine: {
    title: 'Routinearbeiten',
    description: 'Reifenwechsel, Ölwechsel, Inspektionen',
  },
  inspection: {
    title: 'TÜV / AU',
    description: 'Dienstag bis Freitag verfügbar',
  },
  major: {
    title: 'Werkstattaufträge',
    description: 'Reparaturen, umfangreiche Arbeiten',
  },
};

const CATEGORY_ORDER = Object.keys(CATEGORY_CONFIG);

const dayView = document.getElementById('day-view');
const weekView = document.getElementById('week-view');
const selectedDateLabel = document.getElementById('selected-date-label');
const jobModal = document.getElementById('job-modal');
const clipboardModal = document.getElementById('clipboard-modal');
const jobForm = document.getElementById('job-form');
const clipboardForm = document.getElementById('clipboard-form');
const fileInput = document.getElementById('job-files');
const filePreview = document.getElementById('file-preview');
const modalTitle = document.getElementById('modal-title');
const deleteJobButton = document.getElementById('delete-job-btn');
const clipboardList = document.getElementById('clipboard-list');

const state = {
  jobsByDay: new Map(),
  jobsById: new Map(),
  clipboard: [],
};

let currentDate = new Date();
let editingJobId = null;
let editingJobSnapshot = null;

const api = {
  listJobs: () => apiRequest('/api/jobs'),
  createJob: (formData) =>
    apiRequest('/api/jobs', {
      method: 'POST',
      body: formData,
    }),
  updateJob: (id, formData) =>
    apiRequest(`/api/jobs/${id}`, {
      method: 'PUT',
      body: formData,
    }),
  updateJobStatus: (id, status) =>
    apiRequest(`/api/jobs/${id}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    }),
  deleteJob: (id) =>
    apiRequest(`/api/jobs/${id}`, {
      method: 'DELETE',
    }),
  listClipboard: () => apiRequest('/api/clipboard'),
  createClipboard: (payload) =>
    apiRequest('/api/clipboard', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  deleteClipboard: (id) =>
    apiRequest(`/api/clipboard/${id}`, {
      method: 'DELETE',
    }),
};

bindUI();
bootstrap();

async function bootstrap() {
  try {
    await Promise.all([loadJobsFromServer(), loadClipboardFromServer()]);
    render();
  } catch (error) {
    console.error(error);
    alert(error.message || 'Die Werkstattdaten konnten nicht geladen werden.');
  }
}

function bindUI() {
  document.getElementById('day-view-btn').addEventListener('click', showDayView);
  document.getElementById('week-view-btn').addEventListener('click', showWeekView);
  document.getElementById('prev-day').addEventListener('click', () => changeDay(-1));
  document.getElementById('next-day').addEventListener('click', () => changeDay(1));
  document.getElementById('today-btn').addEventListener('click', () => {
    currentDate = new Date();
    render();
  });
  document
    .getElementById('new-job-btn')
    .addEventListener('click', () => openJobModal({ date: formatDateInput(currentDate) }));
  document
    .getElementById('add-clipboard-item')
    .addEventListener('click', () => openClipboardModal());

  jobForm.addEventListener('submit', handleJobSubmit);
  clipboardForm.addEventListener('submit', handleClipboardSubmit);
  fileInput.addEventListener('change', handleFileInput);
  if (deleteJobButton) {
    deleteJobButton.addEventListener('click', handleDeleteJob);
  }

  document.querySelectorAll('[data-close-modal]').forEach((button) => {
    button.addEventListener('click', closeModals);
  });

  [jobModal, clipboardModal].forEach((modal) => {
    modal.addEventListener('click', (event) => {
      if (event.target === modal) closeModals();
    });
  });
}

function render() {
  renderHeader();
  renderDayView();
  renderWeekView();
  renderClipboard();
}

function renderHeader() {
  selectedDateLabel.textContent = currentDate.toLocaleDateString('de-DE', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

function renderDayView() {
  const dayColumns = document.createElement('div');
  dayColumns.className = 'day-columns';

  CATEGORY_ORDER.forEach((category) => {
    const config = CATEGORY_CONFIG[category];
    const column = document.createElement('section');
    column.className = 'day-column';
    const available = isCategoryAvailable(category, currentDate);
    if (!available) column.classList.add('disabled');

    const header = document.createElement('header');
    const title = document.createElement('div');
    title.innerHTML = `<h2>${config.title}</h2><small>${config.description}</small>`;

    const addButton = document.createElement('button');
    addButton.className = 'ghost-button add-job';
    addButton.type = 'button';
    addButton.textContent = 'Auftrag hinzufügen';
    addButton.disabled = !available;
    addButton.addEventListener('click', () =>
      openJobModal({ date: formatDateInput(currentDate), category }),
    );

    header.appendChild(title);
    header.appendChild(addButton);

    const jobList = document.createElement('div');
    jobList.className = 'job-list';
    const jobs = getJobsForDay(currentDate, category);

    if (!jobs.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = 'Noch keine Aufträge angelegt.';
      jobList.appendChild(empty);
    } else {
      jobs.forEach((job) => jobList.appendChild(createJobCard(job)));
    }

    column.appendChild(header);
    column.appendChild(jobList);
    dayColumns.appendChild(column);
  });

  dayView.innerHTML = '';
  dayView.appendChild(dayColumns);
}

function renderWeekView() {
  const startOfWeek = getMonday(currentDate);
  const weekStack = document.createElement('div');
  weekStack.className = 'week-stack';

  for (let i = 0; i < 7; i++) {
    const day = new Date(startOfWeek);
    day.setDate(startOfWeek.getDate() + i);

    const weekDay = document.createElement('section');
    weekDay.className = 'week-day';

    const header = document.createElement('header');
    const title = document.createElement('h3');
    title.textContent = day.toLocaleDateString('de-DE', { weekday: 'long' });
    const label = document.createElement('span');
    label.className = 'week-day-date';
    label.textContent = day.toLocaleDateString('de-DE', {
      day: '2-digit',
      month: '2-digit',
    });

    const addButton = document.createElement('button');
    addButton.className = 'ghost-button small';
    addButton.type = 'button';
    addButton.textContent = '+';
    addButton.setAttribute(
      'aria-label',
      `Auftrag am ${title.textContent} ${label.textContent} anlegen`,
    );
    addButton.addEventListener('click', () => openJobModal({ date: formatDateInput(day) }));

    const heading = document.createElement('div');
    heading.className = 'week-day-heading';
    heading.appendChild(title);
    heading.appendChild(label);

    header.appendChild(heading);
    header.appendChild(addButton);

    const weekColumns = document.createElement('div');
    weekColumns.className = 'week-columns';

    CATEGORY_ORDER.forEach((category) => {
      const config = CATEGORY_CONFIG[category];
      const column = document.createElement('div');
      column.className = 'week-column';
      if (!isCategoryAvailable(category, day)) column.classList.add('disabled');

      const columnTitle = document.createElement('h4');
      columnTitle.textContent = config.title;
      column.appendChild(columnTitle);

      const jobs = getJobsForDay(day, category);

      if (!jobs.length) {
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = 'Keine Aufträge';
        column.appendChild(empty);
      } else {
        jobs.forEach((job) => {
          const jobElement = createWeekJobCard(job);
          column.appendChild(jobElement);
        });
      }

      weekColumns.appendChild(column);
    });

    weekDay.appendChild(header);
    weekDay.appendChild(weekColumns);
    weekStack.appendChild(weekDay);
  }

  weekView.innerHTML = '';
  weekView.appendChild(weekStack);
}

function renderClipboard() {
  clipboardList.innerHTML = '';
  if (!state.clipboard.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'Hier können Sie Aufgaben oder Notizen ablegen.';
    clipboardList.appendChild(empty);
    return;
  }

  const items = [...state.clipboard].sort((a, b) =>
    new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
  );

  items.forEach((item) => {
    const card = document.createElement('article');
    card.className = 'clipboard-card';

    const header = document.createElement('header');
    const title = document.createElement('h3');
    title.textContent = item.title;

    const removeButton = document.createElement('button');
    removeButton.className = 'icon-button';
    removeButton.type = 'button';
    removeButton.textContent = '✕';
    removeButton.addEventListener('click', async () => {
      try {
        await api.deleteClipboard(item.id);
        state.clipboard = state.clipboard.filter((note) => note.id !== item.id);
        renderClipboard();
      } catch (error) {
        console.error(error);
        alert(error.message || 'Notiz konnte nicht entfernt werden.');
      }
    });

    header.appendChild(title);
    header.appendChild(removeButton);

    const body = document.createElement('p');
    body.textContent = item.notes;

    card.appendChild(header);
    card.appendChild(body);
    clipboardList.appendChild(card);
  });
}

function createJobCard(job) {
  const template = document.getElementById('job-card-template');
  const element = template.content.firstElementChild.cloneNode(true);
  element.dataset.jobId = job.id;

  element.querySelector('.job-title').textContent = job.title;
  element.querySelector('.job-time').textContent = job.time || 'Ganztägig';
  element.querySelector('.job-customer').textContent = job.customer || '–';
  element.querySelector('.job-contact').textContent = job.contact || '–';
  element.querySelector('.job-vehicle').textContent = job.vehicle || '–';
  element.querySelector('.job-license').textContent = job.license || '–';

  const notesBlock = element.querySelector('.job-notes-block');
  const notesText = element.querySelector('.job-notes');
  if (job.notes) {
    notesText.textContent = job.notes;
    notesBlock.classList.remove('hidden');
  } else {
    notesText.textContent = '';
    notesBlock.classList.add('hidden');
  }

  const attachmentsBlock = element.querySelector('.job-attachments');
  const attachmentList = attachmentsBlock.querySelector('.attachment-chips');
  attachmentList.innerHTML = '';
  if (job.attachments?.length) {
    attachmentsBlock.classList.remove('hidden');
    job.attachments.forEach((attachment) => {
      const link = document.createElement('a');
      link.className = 'attachment-chip';
      link.href = attachment.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = attachment.name;
      link.addEventListener('click', (event) => event.stopPropagation());
      link.addEventListener('keydown', (event) => event.stopPropagation());
      attachmentList.appendChild(link);
    });
  } else {
    attachmentsBlock.classList.add('hidden');
  }

  const statusToggle = element.querySelector('.status-toggle');
  statusToggle.dataset.status = job.status;
  statusToggle.title = STATUS_LABELS[job.status];
  statusToggle.setAttribute('aria-label', STATUS_LABELS[job.status]);
  statusToggle.style.background = statusColor(job.status);
  statusToggle.addEventListener('click', (event) => {
    event.stopPropagation();
    cycleJobStatus(job);
  });
  statusToggle.addEventListener('keydown', (event) => {
    event.stopPropagation();
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      cycleJobStatus(job);
    }
  });

  element.addEventListener('click', (event) => {
    if (event.target.closest('.status-toggle')) return;
    openJobModal(job);
  });
  element.addEventListener('keydown', (event) => {
    if (event.target.closest('.status-toggle')) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openJobModal(job);
    }
  });

  return element;
}

function createWeekJobCard(job) {
  const element = document.createElement('article');
  element.className = 'week-job';
  element.tabIndex = 0;

  const header = document.createElement('div');
  header.className = 'week-job-header';

  const time = document.createElement('span');
  time.className = 'week-job-time';
  time.textContent = job.time || 'Ganztägig';

  const status = document.createElement('span');
  status.className = 'week-job-status';
  status.title = STATUS_LABELS[job.status];
  status.setAttribute('aria-label', STATUS_LABELS[job.status]);
  status.setAttribute('role', 'img');
  status.style.background = statusColor(job.status);

  header.appendChild(time);
  header.appendChild(status);

  const title = document.createElement('h4');
  title.className = 'week-job-title';
  title.textContent = job.title;

  element.appendChild(header);
  element.appendChild(title);

  const details = document.createElement('div');
  details.className = 'week-job-details';
  [
    ['Kunde', job.customer || '–'],
    ['Kontakt', job.contact || '–'],
    ['Fahrzeug', job.vehicle || '–'],
    ['Kennzeichen', job.license || '–'],
  ].forEach(([label, value]) => {
    const detail = document.createElement('div');
    detail.className = 'week-job-detail';

    const labelEl = document.createElement('span');
    labelEl.className = 'job-label';
    labelEl.textContent = label;

    const valueEl = document.createElement('span');
    valueEl.textContent = value;

    detail.appendChild(labelEl);
    detail.appendChild(valueEl);
    details.appendChild(detail);
  });
  element.appendChild(details);

  if (job.notes) {
    const notes = document.createElement('p');
    notes.className = 'week-job-notes';
    notes.textContent = job.notes;
    element.appendChild(notes);
  }

  if (job.attachments?.length) {
    const attachments = document.createElement('div');
    attachments.className = 'week-job-attachments';

    const label = document.createElement('span');
    label.className = 'job-label';
    label.textContent = 'Anhänge';
    attachments.appendChild(label);

    const list = document.createElement('div');
    list.className = 'attachment-chips';

    job.attachments.forEach((attachment) => {
      const link = document.createElement('a');
      link.className = 'attachment-chip';
      link.href = attachment.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = attachment.name;
      link.addEventListener('click', (event) => event.stopPropagation());
      link.addEventListener('keydown', (event) => event.stopPropagation());
      list.appendChild(link);
    });

    attachments.appendChild(list);
    element.appendChild(attachments);
  }

  element.addEventListener('click', () => openJobModal(job));
  element.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openJobModal(job);
    }
  });

  return element;
}

async function cycleJobStatus(job) {
  const currentIndex = STATUS_SEQUENCE.indexOf(job.status);
  const nextStatus = STATUS_SEQUENCE[(currentIndex + 1) % STATUS_SEQUENCE.length];
  try {
    const updated = await api.updateJobStatus(job.id, nextStatus);
    upsertJob(updated);
    render();
  } catch (error) {
    console.error(error);
    alert(error.message || 'Status konnte nicht aktualisiert werden.');
  }
}

async function handleJobSubmit(event) {
  event.preventDefault();
  const formData = new FormData(jobForm);

  const payload = {
    date: formData.get('date') || formatDateInput(currentDate),
    time: formData.get('time')?.trim() || '',
    category: formData.get('category') || 'routine',
    title: formData.get('title')?.trim() || '',
    customer: formData.get('customer')?.trim() || '',
    contact: formData.get('contact')?.trim() || '',
    vehicle: formData.get('vehicle')?.trim() || '',
    license: formData.get('license')?.trim() || '',
    notes: formData.get('notes')?.trim() || '',
  };

  if (!payload.title) {
    alert('Bitte geben Sie eine Kurzbeschreibung für den Auftrag an.');
    return;
  }

  if (!isCategoryAvailable(payload.category, new Date(payload.date))) {
    alert('Dieser Bereich ist am ausgewählten Tag nicht verfügbar.');
    return;
  }

  const clipboardRequested = formData.get('clipboard');

  formData.set('date', payload.date);
  formData.set('time', payload.time);
  formData.set('category', payload.category);
  formData.set('title', payload.title);
  formData.set('customer', payload.customer);
  formData.set('contact', payload.contact);
  formData.set('vehicle', payload.vehicle);
  formData.set('license', payload.license);
  formData.set('notes', payload.notes);
  formData.delete('clipboard');

  const replaceAttachments = Boolean(editingJobId && fileInput.files.length);
  formData.append('replaceAttachments', replaceAttachments ? 'true' : 'false');

  if (editingJobId) {
    formData.append('status', editingJobSnapshot?.status || 'pending');
  }

  try {
    let job;
    if (editingJobId) {
      job = await api.updateJob(editingJobId, formData);
    } else {
      job = await api.createJob(formData);
    }

    upsertJob(job);

    if (clipboardRequested) {
      const clipboardItem = await api.createClipboard({
        title: job.title,
        notes: `${job.customer || 'Kunde'} • ${new Date(job.date).toLocaleDateString('de-DE')}`,
      });
      state.clipboard.push(clipboardItem);
    }

    closeModals();
    render();
  } catch (error) {
    console.error(error);
    alert(error.message || 'Auftrag konnte nicht gespeichert werden.');
  }
}

async function handleDeleteJob() {
  if (!editingJobId) return;
  if (!confirm('Auftrag wirklich löschen?')) return;

  try {
    await deleteJob(editingJobId);
    closeModals();
    render();
  } catch (error) {
    console.error(error);
    alert(error.message || 'Auftrag konnte nicht gelöscht werden.');
  }
}

async function handleClipboardSubmit(event) {
  event.preventDefault();
  const formData = new FormData(clipboardForm);
  const payload = {
    title: formData.get('title')?.trim() || 'Neue Notiz',
    notes: formData.get('notes')?.trim() || '',
  };

  try {
    const item = await api.createClipboard(payload);
    state.clipboard.push(item);
    closeModals();
    renderClipboard();
  } catch (error) {
    console.error(error);
    alert(error.message || 'Notiz konnte nicht gespeichert werden.');
  }
}

function handleFileInput() {
  renderAttachmentPreview();
}

function renderAttachmentPreview() {
  filePreview.innerHTML = '';
  const existing = editingJobSnapshot?.attachments || [];
  const hasNewFiles = fileInput.files.length > 0;

  if (existing.length) {
    const currentBlock = document.createElement('div');
    currentBlock.className = 'attachment-list';

    const label = document.createElement('span');
    label.className = 'label';
    label.textContent = 'Aktuelle Dateien';
    currentBlock.appendChild(label);

    existing.forEach((attachment) => {
      const link = document.createElement('a');
      link.href = attachment.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = attachment.name;
      currentBlock.appendChild(link);
    });

    filePreview.appendChild(currentBlock);

    if (hasNewFiles) {
      const hint = document.createElement('p');
      hint.className = 'help-text';
      hint.textContent = 'Neue Dateien ersetzen die bestehenden Anhänge.';
      filePreview.appendChild(hint);
    }
  }

  if (!hasNewFiles) return;

  const files = Array.from(fileInput.files);
  const listLabel = document.createElement('span');
  listLabel.className = 'label';
  listLabel.textContent = 'Ausgewählte Dateien';
  filePreview.appendChild(listLabel);

  files.forEach((file, index) => {
    const chip = document.createElement('span');
    chip.className = 'file-chip';
    chip.textContent = file.name;

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = '×';
    remove.addEventListener('click', () => removeFile(index));
    chip.appendChild(remove);
    filePreview.appendChild(chip);
  });
}

function removeFile(index) {
  const dt = new DataTransfer();
  Array.from(fileInput.files).forEach((file, idx) => {
    if (idx !== index) dt.items.add(file);
  });
  fileInput.files = dt.files;
  renderAttachmentPreview();
}

function openJobModal(job = {}) {
  jobForm.reset();
  editingJobId = job.id ?? null;
  editingJobSnapshot = job.id ? structuredCloneSafe(findJob(job.id)) : null;
  const data = editingJobSnapshot || job;

  modalTitle.textContent = editingJobId ? 'Auftrag bearbeiten' : 'Auftrag anlegen';
  if (deleteJobButton) {
    deleteJobButton.classList.toggle('hidden', !editingJobId);
  }

  jobForm.elements.date.value = data.date || formatDateInput(currentDate);
  jobForm.elements.time.value = data.time || '';
  jobForm.elements.category.value = data.category || 'routine';
  jobForm.elements.title.value = data.title || '';
  jobForm.elements.customer.value = data.customer || '';
  jobForm.elements.contact.value = data.contact || '';
  jobForm.elements.vehicle.value = data.vehicle || '';
  jobForm.elements.license.value = data.license || '';
  jobForm.elements.notes.value = data.notes || '';
  jobForm.elements.clipboard.checked = false;

  fileInput.value = '';
  renderAttachmentPreview();

  toggleModal(jobModal, true);
  jobForm.elements.title.focus();
}

function openClipboardModal() {
  clipboardForm.reset();
  toggleModal(clipboardModal, true);
}

async function deleteJob(jobId) {
  await api.deleteJob(jobId);
  removeJobFromState(jobId);
}

function closeModals() {
  editingJobId = null;
  editingJobSnapshot = null;
  jobForm.reset();
  fileInput.value = '';
  filePreview.innerHTML = '';
  clipboardForm.reset();
  if (deleteJobButton) {
    deleteJobButton.classList.add('hidden');
  }
  toggleModal(jobModal, false);
  toggleModal(clipboardModal, false);
}

function toggleModal(modal, open) {
  if (open) {
    modal.classList.remove('hidden');
  } else {
    modal.classList.add('hidden');
  }
}

function changeDay(offset) {
  currentDate.setDate(currentDate.getDate() + offset);
  render();
}

function showDayView() {
  document.getElementById('day-view-btn').classList.add('active');
  document.getElementById('week-view-btn').classList.remove('active');
  dayView.classList.remove('hidden');
  weekView.classList.add('hidden');
}

function showWeekView() {
  document.getElementById('week-view-btn').classList.add('active');
  document.getElementById('day-view-btn').classList.remove('active');
  weekView.classList.remove('hidden');
  dayView.classList.add('hidden');
}

function statusColor(status) {
  switch (status) {
    case 'arrived':
      return 'var(--warning)';
    case 'done':
      return 'var(--success)';
    default:
      return 'var(--danger)';
  }
}

function isCategoryAvailable(category, date) {
  if (category !== 'inspection') return true;
  const weekday = date.getDay();
  return weekday >= 2 && weekday <= 5;
}

function getJobsForDay(date, category) {
  const dayKey = formatDateKey(date);
  const bucket = state.jobsByDay.get(dayKey);
  if (!bucket) return [];
  const jobs = bucket[category] || [];
  return [...jobs].sort((a, b) => (a.time || '').localeCompare(b.time || ''));
}

function upsertJob(job) {
  const existing = state.jobsById.get(job.id);
  if (existing) {
    const originalBucket = state.jobsByDay.get(existing.date);
    if (originalBucket && originalBucket[existing.category]) {
      originalBucket[existing.category] = originalBucket[existing.category].filter(
        (item) => item.id !== job.id,
      );
    }
  }

  if (!state.jobsByDay.has(job.date)) {
    state.jobsByDay.set(job.date, {
      routine: [],
      inspection: [],
      major: [],
    });
  }

  const bucket = state.jobsByDay.get(job.date);
  bucket[job.category].push(job);
  state.jobsById.set(job.id, job);
}

function removeJobFromState(jobId) {
  const job = state.jobsById.get(jobId);
  if (!job) return;

  const bucket = state.jobsByDay.get(job.date);
  if (bucket && bucket[job.category]) {
    bucket[job.category] = bucket[job.category].filter((item) => item.id !== jobId);
    if (!bucket.routine.length && !bucket.inspection.length && !bucket.major.length) {
      state.jobsByDay.delete(job.date);
    }
  }

  state.jobsById.delete(jobId);
}

function findJob(jobId) {
  return state.jobsById.get(jobId) || null;
}

function formatDateKey(date) {
  const clone = new Date(date);
  clone.setHours(0, 0, 0, 0);
  return clone.toISOString().split('T')[0];
}

function formatDateInput(date) {
  return formatDateKey(date);
}

function getMonday(date) {
  const day = date.getDay() || 7;
  const monday = new Date(date);
  monday.setHours(0, 0, 0, 0);
  monday.setDate(date.getDate() - day + 1);
  return monday;
}

async function loadJobsFromServer() {
  const jobs = await api.listJobs();
  state.jobsByDay.clear();
  state.jobsById.clear();
  jobs.forEach((job) => upsertJob(job));
}

async function loadClipboardFromServer() {
  state.clipboard = await api.listClipboard();
}

async function apiRequest(url, options = {}) {
  try {
    const response = await fetch(url, options);
    if (!response.ok) {
      const message = await extractErrorMessage(response);
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }

    if (response.status === 204) {
      return null;
    }

    const contentType = response.headers.get('Content-Type') || '';
    if (contentType.includes('application/json')) {
      return response.json();
    }

    return null;
  } catch (error) {
    if (error.name === 'TypeError') {
      throw new Error('Netzwerkfehler – bitte prüfen Sie die Serververbindung.');
    }
    throw error;
  }
}

async function extractErrorMessage(response) {
  try {
    const data = await response.json();
    if (data && typeof data.error === 'string') {
      return data.error;
    }
  } catch (error) {
    // ignore JSON parse errors
  }
  return 'Es ist ein unbekannter Fehler aufgetreten.';
}

function structuredCloneSafe(value) {
  if (typeof structuredClone === 'function') {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value));
}
