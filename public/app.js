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
const newJobButton = document.getElementById('new-job-btn');
const selectedDateLabel = document.getElementById('selected-date-label');
const calendarToggle = document.getElementById('calendar-toggle');
const calendarDropdown = document.getElementById('calendar-dropdown');
const calendarMonthLabel = document.getElementById('calendar-month-label');
const calendarGrid = document.getElementById('calendar-grid');
const calendarPrev = document.getElementById('calendar-prev');
const calendarNext = document.getElementById('calendar-next');
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

const holidayCache = new Map();

let currentDate = ensureWorkingDate(new Date(), 1);
let calendarMonth = startOfMonth(currentDate);
let calendarOpen = false;
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
  document.getElementById('prev-day').addEventListener('click', () => changeDay(-1));
  document.getElementById('next-day').addEventListener('click', () => changeDay(1));
  document.getElementById('today-btn').addEventListener('click', () => {
    currentDate = ensureWorkingDate(new Date(), 1);
    calendarMonth = startOfMonth(currentDate);
    render();
  });
  if (newJobButton) {
    newJobButton.addEventListener('click', () =>
      openJobModal({ date: formatDateInput(ensureWorkingDate(currentDate, 1)) }),
    );
  }
  document
    .getElementById('add-clipboard-item')
    .addEventListener('click', () => openClipboardModal());

  if (calendarToggle) {
    calendarToggle.addEventListener('click', () => toggleCalendar());
  }
  if (calendarPrev) {
    calendarPrev.addEventListener('click', () => {
      calendarMonth = addMonths(calendarMonth, -1);
      renderCalendar();
    });
  }
  if (calendarNext) {
    calendarNext.addEventListener('click', () => {
      calendarMonth = addMonths(calendarMonth, 1);
      renderCalendar();
    });
  }

  document.addEventListener('click', handleDocumentClick);
  document.addEventListener('keydown', handleCalendarKeydown);

  jobForm.addEventListener('submit', handleJobSubmit);
  const jobDateInput = jobForm.elements.date;
  if (jobDateInput) {
    jobDateInput.addEventListener('change', handleJobDateChange);
  }
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
  renderClipboard();
}

function renderHeader() {
  selectedDateLabel.textContent = currentDate.toLocaleDateString('de-DE', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });

  if (newJobButton) {
    const workingDay = isWorkingDay(currentDate);
    newJobButton.disabled = !workingDay;
    newJobButton.title = workingDay
      ? ''
      : 'An diesem Tag können keine Werkstatt-Termine geplant werden.';
  }

  if (calendarToggle) {
    calendarToggle.setAttribute('aria-expanded', calendarOpen ? 'true' : 'false');
  }

  renderCalendar();
}

function renderDayView() {
  const workingDay = isWorkingDay(currentDate);
  const dayColumns = document.createElement('div');
  dayColumns.className = 'day-columns';

  CATEGORY_ORDER.forEach((category) => {
    const config = CATEGORY_CONFIG[category];
    const column = document.createElement('section');
    column.className = 'day-column';
    const available = workingDay && isCategoryAvailable(category, currentDate);
    if (!available) column.classList.add('disabled');

    const header = document.createElement('header');
    const title = document.createElement('div');
    title.innerHTML = `<h2>${config.title}</h2><small>${config.description}</small>`;

    const addButton = document.createElement('button');
    addButton.className = 'ghost-button add-job';
    addButton.type = 'button';
    addButton.textContent = 'Auftrag hinzufügen';
    addButton.disabled = !available;
    addButton.title = available
      ? ''
      : workingDay
        ? 'Dieser Bereich ist am ausgewählten Tag nicht verfügbar.'
        : 'An diesem Tag können keine Werkstatt-Termine geplant werden.';
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
  if (!workingDay) {
    const notice = document.createElement('div');
    notice.className = 'non-working-notice';
    const { title, message } = describeNonWorkingDay(currentDate);
    const heading = document.createElement('h2');
    heading.textContent = title;
    const paragraph = document.createElement('p');
    paragraph.textContent = message;
    notice.appendChild(heading);
    notice.appendChild(paragraph);
    dayView.appendChild(notice);
  }
  dayView.appendChild(dayColumns);
}

function renderCalendar() {
  if (!calendarGrid || !calendarMonthLabel) return;

  calendarMonth = startOfMonth(calendarMonth);

  calendarMonthLabel.textContent = calendarMonth.toLocaleDateString('de-DE', {
    month: 'long',
    year: 'numeric',
  });

  calendarGrid.innerHTML = '';

  const start = getCalendarStart(calendarMonth);
  const today = startOfDay(new Date());
  const activeDate = startOfDay(currentDate);

  for (let week = 0; week < 6; week++) {
    const row = document.createElement('tr');
    const weekDate = new Date(start);
    weekDate.setDate(start.getDate() + week * 7);

    const weekCell = document.createElement('th');
    weekCell.scope = 'row';
    weekCell.className = 'calendar-week';
    weekCell.textContent = String(getISOWeek(weekDate)).padStart(2, '0');
    row.appendChild(weekCell);

    let containsCurrentMonthDay = false;

    for (let dayIndex = 0; dayIndex < 7; dayIndex++) {
      const cellDate = new Date(start);
      cellDate.setDate(start.getDate() + week * 7 + dayIndex);

      if (cellDate.getMonth() === calendarMonth.getMonth()) {
        containsCurrentMonthDay = true;
      }

      const cell = document.createElement('td');
      cell.className = 'calendar-day';

      if (cellDate.getMonth() !== calendarMonth.getMonth()) {
        cell.classList.add('muted');
      }
      const holidayName = getHolidayName(cellDate);
      const holiday = Boolean(holidayName);
      const disabled = isNonWorkingDay(cellDate);
      if (holiday) {
        cell.classList.add('holiday');
      }
      if (disabled) {
        cell.classList.add('disabled');
      }
      if (isSameDate(cellDate, today)) {
        cell.classList.add('today');
      }
      if (isSameDate(cellDate, activeDate)) {
        cell.classList.add('selected');
      }

      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = String(cellDate.getDate());
      button.disabled = disabled;
      if (disabled) {
        button.title = holiday
          ? `${holidayName} – keine Werkstatt-Termine möglich.`
          : 'Wochenende – keine Werkstatt-Termine möglich.';
      } else {
        button.addEventListener('click', () => {
          currentDate = new Date(cellDate.getFullYear(), cellDate.getMonth(), cellDate.getDate());
          calendarMonth = startOfMonth(currentDate);
          closeCalendar();
          render();
        });
      }

      cell.appendChild(button);
      row.appendChild(cell);
    }

    calendarGrid.appendChild(row);

    if (week >= 4 && !containsCurrentMonthDay) {
      break;
    }
  }
}

function toggleCalendar(force) {
  const nextState = typeof force === 'boolean' ? force : !calendarOpen;
  if (nextState === calendarOpen) {
    if (calendarOpen) {
      renderCalendar();
    }
    return;
  }

  calendarOpen = nextState;

  if (calendarOpen) {
    calendarMonth = startOfMonth(currentDate);
    renderCalendar();
  }

  if (calendarDropdown) {
    calendarDropdown.classList.toggle('hidden', !calendarOpen);
  }

  if (calendarToggle) {
    calendarToggle.setAttribute('aria-expanded', calendarOpen ? 'true' : 'false');
  }
}

function closeCalendar() {
  if (!calendarOpen) return;
  toggleCalendar(false);
}

function handleDocumentClick(event) {
  if (!calendarOpen) return;
  if (calendarDropdown && calendarDropdown.contains(event.target)) return;
  if (calendarToggle && calendarToggle.contains(event.target)) return;
  closeCalendar();
}

function handleCalendarKeydown(event) {
  if (event.key === 'Escape') {
    closeCalendar();
  }
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
  element.querySelector('.job-aw').textContent = job.aw || '–';
  element.querySelector('.job-loaner').textContent = job.loaner ? 'Ja' : 'Nein';
  element.querySelector('.job-tire-storage').textContent = job.tireStorage ? 'Ja' : 'Nein';

  element.classList.toggle('has-loaner', Boolean(job.loaner));
  element.classList.toggle('has-tire-storage', Boolean(job.tireStorage));

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
    aw: formData.get('aw')?.trim() || '',
    loaner: formData.get('loaner') != null,
    tireStorage: formData.get('tireStorage') != null,
  };

  if (!payload.title) {
    alert('Bitte geben Sie eine Kurzbeschreibung für den Auftrag an.');
    return;
  }

  const jobDate = parseInputDate(payload.date);
  if (!jobDate) {
    alert('Bitte wählen Sie ein gültiges Datum aus.');
    return;
  }

  if (isNonWorkingDay(jobDate)) {
    alert('An diesem Datum können keine Werkstatt-Termine geplant werden.');
    return;
  }

  if (!isCategoryAvailable(payload.category, jobDate)) {
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
  formData.set('aw', payload.aw);
  formData.set('loaner', payload.loaner ? 'true' : 'false');
  formData.set('tireStorage', payload.tireStorage ? 'true' : 'false');
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

function handleJobDateChange(event) {
  const input = event.target;
  const value = input.value;
  const parsed = parseInputDate(value);
  if (!parsed || isNonWorkingDay(parsed)) {
    alert('An diesem Datum können keine Werkstatt-Termine geplant werden.');
    const fallback = input.dataset.previousValid
      ? input.dataset.previousValid
      : formatDateInput(ensureWorkingDate(new Date(), 1));
    input.value = fallback;
    input.dataset.previousValid = fallback;
    return;
  }

  input.dataset.previousValid = value;
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

  const defaultDate = data.date || formatDateInput(ensureWorkingDate(currentDate, 1));
  jobForm.elements.date.value = defaultDate;
  const parsedDefault = parseInputDate(defaultDate);
  const fallbackDate =
    parsedDefault && !isNonWorkingDay(parsedDefault)
      ? defaultDate
      : formatDateInput(ensureWorkingDate(parsedDefault || currentDate, 1));
  jobForm.elements.date.dataset.previousValid = fallbackDate;
  jobForm.elements.time.value = data.time || '';
  jobForm.elements.category.value = data.category || 'routine';
  jobForm.elements.title.value = data.title || '';
  jobForm.elements.customer.value = data.customer || '';
  jobForm.elements.contact.value = data.contact || '';
  jobForm.elements.vehicle.value = data.vehicle || '';
  jobForm.elements.license.value = data.license || '';
  jobForm.elements.aw.value = data.aw || '';
  jobForm.elements.loaner.checked = Boolean(data.loaner);
  jobForm.elements.tireStorage.checked = Boolean(data.tireStorage);
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
  if (jobForm.elements.date) {
    delete jobForm.elements.date.dataset.previousValid;
  }
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
  if (!offset) return;
  const direction = offset > 0 ? 1 : -1;
  const steps = Math.abs(offset);
  for (let i = 0; i < steps; i++) {
    currentDate.setDate(currentDate.getDate() + direction);
    let guard = 0;
    while (isNonWorkingDay(currentDate) && guard < 14) {
      currentDate.setDate(currentDate.getDate() + direction);
      guard += 1;
    }
  }
  calendarMonth = startOfMonth(currentDate);
  render();
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
  if (!isWorkingDay(date)) return false;
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

function parseInputDate(value) {
  if (value instanceof Date) {
    const clone = new Date(value);
    clone.setHours(0, 0, 0, 0);
    return clone;
  }
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return null;
  const [year, month, day] = trimmed.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    return null;
  }
  date.setHours(0, 0, 0, 0);
  return date;
}

function ensureWorkingDate(date, direction = 1) {
  const candidate = parseInputDate(date);
  if (!candidate) return new Date();
  if (!isNonWorkingDay(candidate)) {
    return candidate;
  }

  const step = direction >= 0 ? 1 : -1;
  let guard = 0;
  do {
    candidate.setDate(candidate.getDate() + step);
    guard += 1;
  } while (isNonWorkingDay(candidate) && guard < 366);
  return candidate;
}

function isWorkingDay(date) {
  return !isNonWorkingDay(date);
}

function isNonWorkingDay(date) {
  const normalized = parseInputDate(date);
  if (!normalized) return false;
  return isWeekend(normalized) || isHoliday(normalized);
}

function isWeekend(date) {
  const weekday = date.getDay();
  return weekday === 0 || weekday === 6;
}

function isHoliday(date) {
  return Boolean(getHolidayName(date));
}

function getHolidayName(date) {
  const holidays = getNrwHolidays(date.getFullYear());
  return holidays.get(formatDateKey(date)) || null;
}

function getNrwHolidays(year) {
  if (holidayCache.has(year)) {
    return holidayCache.get(year);
  }

  const holidays = new Map();
  holidays.set(`${year}-01-01`, 'Neujahr');

  const easterSunday = calculateEasterSunday(year);
  holidays.set(formatDateKey(addDays(easterSunday, -2)), 'Karfreitag');
  holidays.set(formatDateKey(addDays(easterSunday, 1)), 'Ostermontag');
  holidays.set(`${year}-05-01`, 'Tag der Arbeit');
  holidays.set(formatDateKey(addDays(easterSunday, 39)), 'Christi Himmelfahrt');
  holidays.set(formatDateKey(addDays(easterSunday, 50)), 'Pfingstmontag');
  holidays.set(formatDateKey(addDays(easterSunday, 60)), 'Fronleichnam');
  holidays.set(`${year}-10-03`, 'Tag der Deutschen Einheit');
  holidays.set(`${year}-11-01`, 'Allerheiligen');
  holidays.set(`${year}-12-25`, 'Erster Weihnachtstag');
  holidays.set(`${year}-12-26`, 'Zweiter Weihnachtstag');

  holidayCache.set(year, holidays);
  return holidays;
}

function calculateEasterSunday(year) {
  const a = year % 19;
  const b = Math.floor(year / 100);
  const c = year % 100;
  const d = Math.floor(b / 4);
  const e = b % 4;
  const f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4);
  const k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7;
  const m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31);
  const day = ((h + l - 7 * m + 114) % 31) + 1;
  return new Date(year, month - 1, day);
}

function addDays(date, amount) {
  const result = new Date(date.getTime());
  result.setDate(result.getDate() + amount);
  return result;
}

function describeNonWorkingDay(date) {
  const normalized = parseInputDate(date);
  if (!normalized) {
    return {
      title: 'Keine Werkstatt-Termine',
      message: 'An diesem Tag können keine Termine geplant werden.',
    };
  }

  if (isWeekend(normalized)) {
    const dayName = normalized.toLocaleDateString('de-DE', { weekday: 'long' });
    return {
      title: `${dayName}: Werkstatt geschlossen`,
      message: 'An Wochenenden können keine Werkstatt-Termine geplant werden.',
    };
  }

  const holidayName = getHolidayName(normalized) || 'Feiertag in NRW';
  const dayLabel = normalized.toLocaleDateString('de-DE', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });
  return {
    title: `${holidayName}: Werkstatt geschlossen`,
    message: `${dayLabel} ist ein gesetzlicher Feiertag in Nordrhein-Westfalen. Termine sind nicht verfügbar.`,
  };
}

function startOfDay(date) {
  const clone = new Date(date);
  clone.setHours(0, 0, 0, 0);
  return clone;
}

function startOfMonth(date) {
  return startOfDay(new Date(date.getFullYear(), date.getMonth(), 1));
}

function addMonths(date, amount) {
  const clone = startOfMonth(date);
  clone.setMonth(clone.getMonth() + amount);
  return clone;
}

function getCalendarStart(monthDate) {
  const start = startOfMonth(monthDate);
  const weekday = (start.getDay() + 6) % 7; // Monday = 0
  start.setDate(start.getDate() - weekday);
  return start;
}

function getISOWeek(date) {
  const target = startOfDay(date);
  const dayNr = (target.getDay() + 6) % 7;
  target.setDate(target.getDate() - dayNr + 3);
  const firstThursday = new Date(target.getFullYear(), 0, 4);
  const firstThursdayDayNr = (firstThursday.getDay() + 6) % 7;
  firstThursday.setDate(firstThursday.getDate() - firstThursdayDayNr + 3);
  const diff = target - firstThursday;
  return 1 + Math.round(diff / (7 * 24 * 60 * 60 * 1000));
}

function isSameDate(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
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
