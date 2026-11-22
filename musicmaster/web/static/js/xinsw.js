/* 心思维单入口测试页：只走主唱 CREPE 自动识别，不暴露算法选项。 */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var fileInput = $('audio'), drop = $('drop'), start = $('start'), clear = $('clear');\n  var autoSeparate = $('autoSeparate');
  var fileInfo = $('fileInfo'), preview = $('preview'), progressPanel = $('progressPanel');
  var stage = $('stage'), pct = $('pct'), fill = $('fill'), progressMessage = $('progressMessage');
  var resultPanel = $('resultPanel'), resultTitle = $('resultTitle'), resultMessage = $('resultMessage');
  var confidence = $('confidence'), score = $('score'), downloads = $('downloads'), report = $('report');
  var selectedFile = null, objectUrl = null, busy = false;

  function sizeText(bytes) {
    if (bytes >= 1024 * 1024) return (bytes / 1024 / 1024).toFixed(2) + ' MB';
    return (bytes / 1024).toFixed(1) + ' KB';
  }
  function setFile(file) {
    if (!file) return;
    if (!file.type.startsWith('audio/') && !/\.(mp3|wav|m4a|flac|ogg|aac)$/i.test(file.name)) {
      selectedFile = null; start.disabled = true;
      progressMessage.textContent = '文件格式看起来不是音频，请选择 MP3、WAV、M4A 或 FLAC。';
      progressPanel.classList.remove('hidden');
      return;
    }
    selectedFile = file;
    fileInfo.textContent = file.name + ' · ' + sizeText(file.size);
    fileInfo.style.display = 'block';
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(file);
    preview.src = objectUrl;
    preview.style.display = 'block';
    start.disabled = false;
    progressPanel.classList.add('hidden');
    resultPanel.classList.add('hidden');
  }
  fileInput.addEventListener('change', function () { setFile(fileInput.files && fileInput.files[0]); });
  ['dragenter', 'dragover'].forEach(function (name) {
    drop.addEventListener(name, function (event) { event.preventDefault(); drop.classList.add('drag'); });
  });
  ['dragleave', 'drop'].forEach(function (name) {
    drop.addEventListener(name, function (event) {
      event.preventDefault(); drop.classList.remove('drag');
      if (name === 'drop' && event.dataTransfer.files.length) setFile(event.dataTransfer.files[0]);
    });
  });

  function updateProgress(job) {
    var p = Math.max(0, Math.min(100, Math.round((Number(job.progress) || 0) * 100)));
    stage.textContent = job.stage || (job.status === 'queued' ? '排队中' : '处理中');
    pct.textContent = p + '%';
    fill.style.width = p + '%';
    progressMessage.textContent = job.status === 'queued'
      ? '任务已提交，等待处理资源。'
      : '当前阶段：' + (job.stage || '处理中') + '。页面显示服务端实际报告的阶段与进度，不使用模拟百分比。';
  }

  function fileUrl(jobId, name) {
    var encoded = String(name).split('/').map(encodeURIComponent).join('/');
    return '/api/file/' + encodeURIComponent(jobId) + '/' + encoded;
  }
  function renderResult(job) {
    var result = job.result || {};
    resultPanel.classList.remove('hidden');
    resultTitle.textContent = result.source_mode === 'full-song'\n      ? (result.ok ? '完整歌曲扒谱完成' : '完整歌曲处理结束，请查看报告')\n      : (result.ok ? '主唱识别完成' : '识别任务已结束，请查看报告');
    resultMessage.textContent = result.message || (result.ok
      ? '已生成识别产物。请先试听并检查谱面，重点核对八度、短音和节奏。'
      : '本次没有通过识别流程。报告会保留可用的诊断信息。');
    confidence.textContent = result.confidence_pct == null ? '' : '整体可信度 ' + result.confidence_pct + '%';
    if (result.staff_svg) {
      score.innerHTML = result.staff_svg;
      score.classList.remove('hidden');
    } else {
      score.innerHTML = '';
      score.classList.add('hidden');
    }
    downloads.innerHTML = '';
    (result.downloads || []).forEach(function (item) {
      var a = document.createElement('a');
      var friendly = item.download || String(item.name).split('/').pop();
      a.href = fileUrl(job.id, item.name) + '?as=' + encodeURIComponent(friendly);
      a.setAttribute('download', friendly);
      var label = document.createElement('strong');
      label.textContent = item.label || friendly;
      var small = document.createElement('small');
      small.textContent = friendly + (item.size_kb ? ' · ' + sizeText(item.size_kb * 1024) : '');
      a.appendChild(label); a.appendChild(small); downloads.appendChild(a);
    });
    if (!downloads.children.length) downloads.textContent = '本次没有可下载文件。';
    report.textContent = result.report_md || result.message || job.error || '没有生成文字报告。';
  }

  function poll(jobId) {
    fetch('/api/job/' + encodeURIComponent(jobId))
      .then(function (response) {
        if (!response.ok) throw new Error('查询任务失败：HTTP ' + response.status);
        return response.json();
      })
      .then(function (job) {
        updateProgress(job);
        if (job.status === 'done') {
          fill.style.width = '100%'; pct.textContent = '100%';
          renderResult(job); busy = false; start.disabled = !selectedFile; clear.disabled = false;
          return;
        }
        if (job.status === 'error') {
          stage.textContent = '处理出错'; progressMessage.textContent = job.error || '服务端任务失败。';
          progressMessage.classList.add('error');
          busy = false; start.disabled = !selectedFile; clear.disabled = false;
          return;
        }
        window.setTimeout(function () { poll(jobId); }, 900);
      })
      .catch(function (error) {
        stage.textContent = '连接中断'; progressMessage.textContent = error.message;
        progressMessage.classList.add('error');
        busy = false; start.disabled = !selectedFile; clear.disabled = false;
      });
  }

  start.addEventListener('click', function () {
    if (!selectedFile || busy) return;
    busy = true; start.disabled = true; clear.disabled = true;
    resultPanel.classList.add('hidden'); progressPanel.classList.remove('hidden');
    progressMessage.classList.remove('error');
    stage.textContent = '正在提交'; pct.textContent = '0%'; fill.style.width = '0%';
    var form = new FormData();
    form.append('audio', selectedFile, selectedFile.name);
    form.append('engine', 'crepe');
    form.append('key', '');\n    form.append('auto_separate', autoSeparate && autoSeparate.checked ? 'true' : 'false');
    fetch('/api/transcribe', { method: 'POST', body: form })
      .then(function (response) {
        if (!response.ok) return response.text().then(function (body) {
          throw new Error('上传或提交失败：HTTP ' + response.status + ' ' + body);
        });
        return response.json();
      })
      .then(function (data) {
        if (!data.job_id) throw new Error('服务端没有返回任务编号。');
        stage.textContent = '任务已提交';
        poll(data.job_id);
      })
      .catch(function (error) {
        stage.textContent = '提交失败'; progressMessage.textContent = error.message;
        progressMessage.classList.add('error');
        busy = false; start.disabled = !selectedFile; clear.disabled = false;
      });
  });

  clear.addEventListener('click', function () {
    if (busy) return;
    selectedFile = null; fileInput.value = '';
    fileInfo.textContent = ''; fileInfo.style.display = 'none';
    preview.pause(); preview.removeAttribute('src'); preview.load(); preview.style.display = 'none';
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null; start.disabled = true;
    progressPanel.classList.add('hidden'); resultPanel.classList.add('hidden');
    progressMessage.classList.remove('error');
  });
})();
