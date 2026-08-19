const form = document.querySelector('#studioForm');
const modes = [...document.querySelectorAll('input[name="mode"]')];
const referenceField = document.querySelector('#referenceField');
const promptField = document.querySelector('#promptField');
const controlField = document.querySelector('#controlField');
const referenceInput = document.querySelector('#referenceAudio');
const referencePreview = document.querySelector('#referencePreview');
const dropzone = document.querySelector('#dropzone');
const dropCopy = document.querySelector('#dropCopy');
const targetText = document.querySelector('#targetText');
const generateButton = document.querySelector('#generateButton');
const result = document.querySelector('#result');
const resultAudio = document.querySelector('#resultAudio');
const downloadLink = document.querySelector('#downloadLink');
const emptyState = document.querySelector('#emptyState');
const errorBox = document.querySelector('#errorBox');
let referenceObjectUrl;
let recorder;
let recordedChunks = [];

function selectedMode() { return modes.find((item) => item.checked).value; }

function updateMode() {
  const mode = selectedMode();
  document.querySelectorAll('.mode-card').forEach((card) => card.classList.toggle('active', card.querySelector('input').checked));
  referenceField.hidden = mode === 'design';
  promptField.hidden = mode !== 'ultimate';
  controlField.hidden = mode === 'ultimate';
}
modes.forEach((item) => item.addEventListener('change', updateMode));

targetText.addEventListener('input', () => { document.querySelector('#charCount').textContent = targetText.value.length; });
document.querySelector('#cfgValue').addEventListener('input', (event) => { document.querySelector('#cfgOutput').textContent = Number(event.target.value).toFixed(1); });
document.querySelector('#steps').addEventListener('input', (event) => { document.querySelector('#stepsOutput').textContent = event.target.value; });
document.querySelectorAll('[data-prompt]').forEach((button) => button.addEventListener('click', () => { document.querySelector('#control').value = button.dataset.prompt; }));

function showReference(file) {
  if (!file) return;
  if (referenceObjectUrl) URL.revokeObjectURL(referenceObjectUrl);
  referenceObjectUrl = URL.createObjectURL(file);
  referencePreview.src = referenceObjectUrl;
  referencePreview.hidden = false;
  dropCopy.hidden = true;
}
referenceInput.addEventListener('change', () => showReference(referenceInput.files[0]));
['dragenter', 'dragover'].forEach((name) => dropzone.addEventListener(name, () => dropzone.classList.add('dragging')));
['dragleave', 'drop'].forEach((name) => dropzone.addEventListener(name, () => dropzone.classList.remove('dragging')));

document.querySelector('#recordButton').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  if (recorder?.state === 'recording') { recorder.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordedChunks = [];
    recorder = new MediaRecorder(stream);
    recorder.addEventListener('dataavailable', (e) => { if (e.data.size) recordedChunks.push(e.data); });
    recorder.addEventListener('stop', () => {
      const blob = new Blob(recordedChunks, { type: recorder.mimeType || 'audio/webm' });
      const file = new File([blob], 'microphone.webm', { type: blob.type });
      const transfer = new DataTransfer(); transfer.items.add(file); referenceInput.files = transfer.files;
      showReference(file);
      stream.getTracks().forEach((track) => track.stop());
      button.classList.remove('recording'); button.innerHTML = '<span></span> 使用麥克風錄音';
    });
    recorder.start();
    button.classList.add('recording'); button.innerHTML = '<span></span> 停止並使用錄音';
  } catch (error) {
    showError(`無法使用麥克風：${error.message}`);
  }
});

function showError(message) { errorBox.textContent = message; errorBox.hidden = false; }

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  errorBox.hidden = true;
  const data = new FormData(form);
  if (!data.get('normalize')) data.set('normalize', 'false');
  if (!data.get('denoise')) data.set('denoise', 'false');
  if (!data.get('seed')) data.delete('seed');
  if (selectedMode() === 'design') data.delete('reference_audio');

  generateButton.disabled = true;
  generateButton.classList.add('loading');
  try {
    const response = await fetch('/api/generate', { method: 'POST', body: data });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `伺服器錯誤 (${response.status})`);
    resultAudio.src = `${payload.audio_url}?t=${Date.now()}`;
    downloadLink.href = payload.audio_url;
    downloadLink.download = payload.filename;
    result.hidden = false;
    emptyState.hidden = true;
    resultAudio.play().catch(() => {});
  } catch (error) {
    showError(error.message);
  } finally {
    generateButton.disabled = false;
    generateButton.classList.remove('loading');
  }
});

async function checkStatus() {
  const status = document.querySelector('#serverStatus');
  try {
    const response = await fetch('/api/status');
    const info = await response.json();
    status.className = `status ${info.error ? 'error' : 'ready'}`;
    status.querySelector('em').textContent = info.error ? '模型需檢查' : (info.ready ? '模型已就緒' : '伺服器已連線');
  } catch { status.className = 'status error'; status.querySelector('em').textContent = '伺服器離線'; }
}
updateMode(); checkStatus();
