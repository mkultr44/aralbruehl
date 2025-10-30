const path = require('path');
const fs = require('fs');
const express = require('express');
const multer = require('multer');
const db = require('./database');

const app = express();
const PORT = process.env.PORT || 3000;

const uploadDir = path.join(__dirname, 'uploads');
if (!fs.existsSync(uploadDir)) {
  fs.mkdirSync(uploadDir, { recursive: true });
}

const storage = multer.diskStorage({
  destination: uploadDir,
  filename: (_req, file, callback) => {
    const timestamp = Date.now();
    const random = Math.random().toString(16).slice(2, 10);
    const safeName = file.originalname.replace(/[^a-zA-Z0-9_.-]+/g, '_');
    callback(null, `${timestamp}-${random}-${safeName}`);
  },
});

const upload = multer({ storage });

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use('/uploads', express.static(uploadDir));
app.use(express.static(path.join(__dirname, 'public')));

const HOLIDAY_CACHE = new Map();

const JOB_COLUMNS = `
  id,
  date,
  time,
  category,
  title,
  customer,
  contact,
  vehicle,
  license,
  notes,
  aw,
  loaner,
  tire_storage,
  status,
  created_at,
  updated_at
`;

const selectJobById = db.prepare(`SELECT ${JOB_COLUMNS} FROM jobs WHERE id = ?`);
const selectAllJobs = db.prepare(`SELECT ${JOB_COLUMNS} FROM jobs ORDER BY date, time`);
const insertJobStmt = db.prepare(
  `INSERT INTO jobs (date, time, category, title, customer, contact, vehicle, license, notes, aw, loaner, tire_storage, status)
   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
);
const updateJobStmt = db.prepare(
  `UPDATE jobs
     SET date = ?,
         time = ?,
         category = ?,
         title = ?,
         customer = ?,
         contact = ?,
         vehicle = ?,
         license = ?,
         notes = ?,
         aw = ?,
         loaner = ?,
         tire_storage = ?,
         status = ?,
         updated_at = CURRENT_TIMESTAMP
   WHERE id = ?`
);
const updateStatusStmt = db.prepare(
  'UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?'
);
const deleteJobStmt = db.prepare('DELETE FROM jobs WHERE id = ?');
const deleteAttachmentsStmt = db.prepare('DELETE FROM attachments WHERE job_id = ?');
const selectAttachmentsForJob = db.prepare(
  'SELECT id, original_name, stored_name, mime_type, size FROM attachments WHERE job_id = ? ORDER BY id'
);
const insertAttachmentStmt = db.prepare(
  `INSERT INTO attachments (job_id, original_name, stored_name, mime_type, size)
   VALUES (?, ?, ?, ?, ?)`
);
const selectClipboard = db.prepare(
  'SELECT id, title, notes, created_at FROM clipboard ORDER BY created_at DESC, id DESC'
);
const selectClipboardById = db.prepare(
  'SELECT id, title, notes, created_at FROM clipboard WHERE id = ?'
);
const insertClipboardStmt = db.prepare(
  'INSERT INTO clipboard (title, notes) VALUES (?, ?)'
);
const deleteClipboardStmt = db.prepare('DELETE FROM clipboard WHERE id = ?');

app.get('/api/jobs', (_req, res, next) => {
  try {
    const jobs = selectAllJobs.all().map(attachJobResources);
    res.json(jobs);
  } catch (error) {
    next(error);
  }
});

app.post('/api/jobs', upload.array('files'), (req, res, next) => {
  try {
    const payload = parseJobPayload(req.body);
    const jobId = createJob(payload, req.files || []);
    const job = getJobById(jobId);
    res.status(201).json(job);
  } catch (error) {
    next(error);
  }
});

app.put('/api/jobs/:id', upload.array('files'), (req, res, next) => {
  try {
    const jobId = parseId(req.params.id);
    const existing = selectJobById.get(jobId);
    if (!existing) {
      throw createHttpError(404, 'Auftrag wurde nicht gefunden.');
    }

    const payload = parseJobPayload({ ...existing, ...req.body }, {
      defaultStatus: existing.status,
    });
    const replaceAttachments = req.body.replaceAttachments === 'true';
    const attachmentsToRemove = replaceAttachments
      ? selectAttachmentsForJob.all(jobId)
      : [];

    updateJob(jobId, payload, req.files || [], replaceAttachments);

    attachmentsToRemove.forEach((attachment) => removeStoredFile(attachment.stored_name));

    const job = getJobById(jobId);
    res.json(job);
  } catch (error) {
    next(error);
  }
});

app.patch('/api/jobs/:id/status', (req, res, next) => {
  try {
    const jobId = parseId(req.params.id);
    const status = validateStatus(req.body.status);
    const existing = selectJobById.get(jobId);
    if (!existing) {
      throw createHttpError(404, 'Auftrag wurde nicht gefunden.');
    }

    updateStatusStmt.run(status, jobId);
    const job = getJobById(jobId);
    res.json(job);
  } catch (error) {
    next(error);
  }
});

app.delete('/api/jobs/:id', (req, res, next) => {
  try {
    const jobId = parseId(req.params.id);
    const existing = selectJobById.get(jobId);
    if (!existing) {
      throw createHttpError(404, 'Auftrag wurde nicht gefunden.');
    }

    const attachments = selectAttachmentsForJob.all(jobId);
    const result = deleteJobStmt.run(jobId);
    if (!result.changes) {
      throw createHttpError(404, 'Auftrag wurde nicht gefunden.');
    }

    attachments.forEach((attachment) => removeStoredFile(attachment.stored_name));

    res.status(204).end();
  } catch (error) {
    next(error);
  }
});

app.get('/api/clipboard', (_req, res, next) => {
  try {
    const items = selectClipboard.all().map(mapClipboardRow);
    res.json(items);
  } catch (error) {
    next(error);
  }
});

app.post('/api/clipboard', (req, res, next) => {
  try {
    const title = ensureText(req.body.title, 'Titel ist erforderlich.');
    const notes = ensureText(req.body.notes, 'Bitte geben Sie eine Notiz ein.');
    const result = insertClipboardStmt.run(title, notes);
    const item = selectClipboardById.get(result.lastInsertRowid);
    res.status(201).json(mapClipboardRow(item));
  } catch (error) {
    next(error);
  }
});

app.delete('/api/clipboard/:id', (req, res, next) => {
  try {
    const itemId = parseId(req.params.id);
    const result = deleteClipboardStmt.run(itemId);
    if (!result.changes) {
      throw createHttpError(404, 'Notiz wurde nicht gefunden.');
    }
    res.status(204).end();
  } catch (error) {
    next(error);
  }
});

app.get('*', (req, res, next) => {
  if (req.path.startsWith('/api/')) {
    return next();
  }
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.use((err, _req, res, _next) => {
  console.error(err);
  const status = Number.isInteger(err.status) ? err.status : 500;
  const message = err.message || 'Interner Serverfehler.';
  res.status(status).json({ error: message });
});

if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`Werkstattplaner läuft auf http://localhost:${PORT}`);
  });
}

module.exports = app;

function createJob(payload, files) {
  return insertJobTransaction(payload, files || []);
}

const insertJobTransaction = db.transaction((payload, files) => {
  const result = insertJobStmt.run(
    payload.date,
    payload.time ?? null,
    payload.category,
    payload.title,
    payload.customer ?? null,
    payload.contact ?? null,
    payload.vehicle ?? null,
    payload.license ?? null,
    payload.notes ?? null,
    payload.aw ?? null,
    payload.loaner ?? 0,
    payload.tireStorage ?? 0,
    payload.status,
  );
  const jobId = Number(result.lastInsertRowid);

  files.forEach((file) => {
    insertAttachmentStmt.run(jobId, file.originalname, file.filename, file.mimetype, file.size);
  });

  return jobId;
});

function updateJob(jobId, payload, files, replaceAttachments) {
  updateJobTransaction(jobId, payload, files || [], replaceAttachments);
}

const updateJobTransaction = db.transaction((jobId, payload, files, replaceAttachments) => {
  updateJobStmt.run(
    payload.date,
    payload.time ?? null,
    payload.category,
    payload.title,
    payload.customer ?? null,
    payload.contact ?? null,
    payload.vehicle ?? null,
    payload.license ?? null,
    payload.notes ?? null,
    payload.aw ?? null,
    payload.loaner ?? 0,
    payload.tireStorage ?? 0,
    payload.status,
    jobId,
  );

  if (replaceAttachments) {
    deleteAttachmentsStmt.run(jobId);
  }

  files.forEach((file) => {
    insertAttachmentStmt.run(jobId, file.originalname, file.filename, file.mimetype, file.size);
  });
});

function getJobById(jobId) {
  const row = selectJobById.get(jobId);
  if (!row) return null;
  return attachJobResources(row);
}

function attachJobResources(row) {
  const attachments = selectAttachmentsForJob.all(row.id).map(mapAttachmentRow);
  return {
    id: row.id,
    date: row.date,
    time: row.time || '',
    category: row.category,
    title: row.title,
    customer: row.customer || '',
    contact: row.contact || '',
    vehicle: row.vehicle || '',
    license: row.license || '',
    notes: row.notes || '',
    aw: row.aw || '',
    loaner: Boolean(row.loaner),
    tireStorage: Boolean(row.tire_storage),
    status: row.status,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    attachments,
  };
}

function mapAttachmentRow(row) {
  return {
    id: row.id,
    name: row.original_name,
    url: `/uploads/${row.stored_name}`,
    mimeType: row.mime_type || '',
    size: row.size || 0,
  };
}

function mapClipboardRow(row) {
  return {
    id: row.id,
    title: row.title,
    notes: row.notes,
    createdAt: row.created_at,
  };
}

function parseJobPayload(body, options = {}) {
  const date = normalizeDate(body.date);
  if (!date) {
    throw createHttpError(400, 'Bitte ein gültiges Datum angeben.');
  }

  if (!isWorkingDate(date)) {
    throw createHttpError(400, 'An diesem Datum können keine Werkstatt-Termine geplant werden.');
  }

  const category = validateCategory(body.category);
  if (category === 'inspection' && !isInspectionDate(date)) {
    throw createHttpError(400, 'TÜV / AU ist nur Dienstag bis Freitag verfügbar.');
  }

  const tireStorage = normalizeBoolean(body.tireStorage ?? body.tire_storage) ? 1 : 0;

  return {
    date,
    time: normalizeTime(body.time),
    category,
    title: ensureText(body.title, 'Bitte geben Sie eine Kurzbeschreibung an.'),
    customer: optionalText(body.customer),
    contact: optionalText(body.contact),
    vehicle: optionalText(body.vehicle),
    license: optionalText(body.license),
    notes: optionalText(body.notes),
    aw: optionalText(body.aw),
    loaner: normalizeBoolean(body.loaner) ? 1 : 0,
    tireStorage,
    status: validateStatus(body.status ?? options.defaultStatus ?? 'pending'),
  };
}

function normalizeDate(value) {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) return null;
  const [year, month, day] = trimmed.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    return null;
  }
  return trimmed;
}

function normalizeTime(value) {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (!/^\d{2}:\d{2}$/.test(trimmed)) {
    throw createHttpError(400, 'Bitte eine gültige Uhrzeit im Format HH:MM angeben.');
  }
  return trimmed;
}

const VALID_CATEGORIES = new Set(['routine', 'inspection', 'major']);

function validateCategory(value) {
  const category = typeof value === 'string' && value.trim() ? value.trim() : 'routine';
  if (!VALID_CATEGORIES.has(category)) {
    throw createHttpError(400, 'Ungültiger Arbeitsbereich.');
  }
  return category;
}

const VALID_STATUS = new Set(['pending', 'arrived', 'done']);

function validateStatus(value) {
  const status = typeof value === 'string' && value.trim() ? value.trim() : 'pending';
  if (!VALID_STATUS.has(status)) {
    throw createHttpError(400, 'Ungültiger Auftragsstatus.');
  }
  return status;
}

function ensureText(value, errorMessage) {
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text) {
    throw createHttpError(400, errorMessage);
  }
  return text;
}

function optionalText(value) {
  const text = typeof value === 'string' ? value.trim() : '';
  return text || null;
}

function normalizeBoolean(value) {
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    return normalized === 'true' || normalized === 'on' || normalized === '1' || normalized === 'ja';
  }

  if (typeof value === 'number') {
    return value === 1;
  }

  return Boolean(value);
}

function parseId(value) {
  const id = Number.parseInt(value, 10);
  if (!Number.isInteger(id)) {
    throw createHttpError(400, 'Ungültige ID.');
  }
  return id;
}

function isInspectionDate(dateString) {
  const date = parseISODate(dateString);
  if (!date) return false;
  if (!isWorkingDate(dateString)) return false;
  const weekday = date.getDay();
  return weekday >= 2 && weekday <= 5;
}

function isWorkingDate(dateString) {
  const date = parseISODate(dateString);
  if (!date) return false;
  return !isWeekend(date) && !isNrwHoliday(date);
}

function parseISODate(dateString) {
  if (typeof dateString !== 'string') return null;
  const parts = dateString.split('-').map(Number);
  if (parts.length !== 3 || parts.some((part) => Number.isNaN(part))) {
    return null;
  }
  const [year, month, day] = parts;
  const date = new Date(year, month - 1, day);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
    return null;
  }
  return date;
}

function isWeekend(date) {
  const weekday = date.getDay();
  return weekday === 0 || weekday === 6;
}

function isNrwHoliday(date) {
  const holidays = getNrwHolidays(date.getFullYear());
  return holidays.has(formatISODate(date));
}

function getNrwHolidays(year) {
  if (HOLIDAY_CACHE.has(year)) {
    return HOLIDAY_CACHE.get(year);
  }

  const holidays = new Set();
  holidays.add(`${year}-01-01`); // Neujahr

  const easterSunday = calculateEasterSunday(year);
  holidays.add(formatISODate(addDays(easterSunday, -2))); // Karfreitag
  holidays.add(formatISODate(addDays(easterSunday, 1))); // Ostermontag
  holidays.add(`${year}-05-01`); // Tag der Arbeit
  holidays.add(formatISODate(addDays(easterSunday, 39))); // Christi Himmelfahrt
  holidays.add(formatISODate(addDays(easterSunday, 50))); // Pfingstmontag
  holidays.add(formatISODate(addDays(easterSunday, 60))); // Fronleichnam
  holidays.add(`${year}-10-03`); // Tag der Deutschen Einheit
  holidays.add(`${year}-11-01`); // Allerheiligen
  holidays.add(`${year}-12-25`); // 1. Weihnachtstag
  holidays.add(`${year}-12-26`); // 2. Weihnachtstag

  HOLIDAY_CACHE.set(year, holidays);
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
  const copy = new Date(date.getTime());
  copy.setDate(copy.getDate() + amount);
  return copy;
}

function formatISODate(date) {
  return date.toISOString().split('T')[0];
}

function createHttpError(status, message) {
  const error = new Error(message);
  error.status = status;
  return error;
}

function removeStoredFile(filename) {
  if (!filename) return;
  const filePath = path.join(uploadDir, filename);
  fs.promises.unlink(filePath).catch((error) => {
    if (error && error.code !== 'ENOENT') {
      console.error(`Datei ${filePath} konnte nicht gelöscht werden:`, error);
    }
  });
}
