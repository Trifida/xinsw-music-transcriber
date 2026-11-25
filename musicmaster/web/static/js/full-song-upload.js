/* Full-song upload entry for the transcription panel.
 * This submits the original mixed recording to the durable cloud-job API.
 * GPU provisioning is opt-in; queue status and completed artifact downloads are shown explicitly.
 */
(function () {
  'use strict';

  function init() {
    var fileInput = document.getElementById('full-song-file');
    var filename = document.getElementById('full-song-filename');
    var lyricsInput = document.getElementById('full-song-lyrics');
    var submit = document.getElementById('full-song-submit');
    var status = document.getElementById('full-song-status');
    var refresh = document.getElementById('full-song-refresh');
    var start = document.getElementById('full-song-start');
    var artifactsContainer = document.getElementById('full-song-artifacts');
    if (!fileInput || !submit || !status || !refresh || !start) return;

    var sourceOptions = document.querySelectorAll('input[name="tr"]');
    var singleAudioInput = document.getElementById('single-audio-input');
    var singleSourceFields = document.getElementById('single-source-fields');
    var fullSongFields = document.getElementById('full-song-fields');

    function showSelectedSource() {
      var selected = document.querySelector('input[name="tr"]:checked');
      var fullSongMode = !!selected && selected.value === 'full-song';
      if (singleAudioInput) singleAudioInput.hidden = fullSongMode;
      if (singleSourceFields) singleSourceFields.hidden = fullSongMode;
      if (fullSongFields) fullSongFields.hidden = !fullSongMode;
    }

    Array.prototype.forEach.call(sourceOptions, function (option) {
      option.addEventListener('change', showSelectedSource);
    });
    showSelectedSource();

    var JOB_STORAGE_KEY = 'xinsw.fullSong.activeJobId';

    function readSavedJobId() {
      try { return window.sessionStorage.getItem(JOB_STORAGE_KEY) || ''; }
      catch (_) { return ''; }
    }

    function saveJobId(jobId) {
      try {
        if (jobId) window.sessionStorage.setItem(JOB_STORAGE_KEY, jobId);
        else window.sessionStorage.removeItem(JOB_STORAGE_KEY);
      } catch (_) {
        // The workflow remains usable when browser storage is unavailable.
      }
    }

    var activeJobId = readSavedJobId();
    var autoPoll = false;
    var pollTimer = null;
    var queryInFlight = false;
    var startRequestInFlight = false;

    function setBusy(busy) {
      submit.disabled = busy;
      submit.style.opacity = busy ? '.65' : '';
      submit.style.pointerEvents = busy ? 'none' : '';
      submit.setAttribute('aria-busy', busy ? 'true' : 'false');
    }

    function uploadFullSong(body) {
      return new Promise(function (resolve, reject) {
        var request = new XMLHttpRequest();
        request.open('POST', '/api/cloud/jobs');
        request.timeout = 15 * 60 * 1000;
        request.upload.addEventListener('progress', function (event) {
          if (!event.lengthComputable) return;
          var percent = Math.min(100, Math.round(event.loaded / event.total * 100));
          status.textContent = '正在上传完整歌曲：' + percent + '%';
        });
        request.addEventListener('load', function () {
          var data = {};
          try { data = JSON.parse(request.responseText || '{}'); }
          catch (_) { data = {}; }
          if (request.status < 200 || request.status >= 300) {
            reject(new Error(data.detail || data.message || ('HTTP ' + request.status)));
            return;
          }
          resolve(data);
        });
        request.addEventListener('error', function () {
          reject(new Error('网络连接中断，请检查网络后重试。'));
        });
        request.addEventListener('timeout', function () {
          reject(new Error('上传等待时间过长，请检查网络后重试。'));
        });
        request.addEventListener('abort', function () {
          reject(new Error('上传已取消。'));
        });
        request.send(body);
      });
    }

    function renderArtifactLinks(artifacts) {
      if (!artifactsContainer) return;
      artifactsContainer.textContent = '';
      (artifacts || []).forEach(function (item) {
        if (!item || item.id == null) return;
        var row = document.createElement('div');
        row.textContent = '正在准备下载：' + (item.file_name || item.name || '文件');
        artifactsContainer.appendChild(row);
        var endpoint = '/api/cloud/jobs/' + encodeURIComponent(activeJobId)
          + '/artifacts/' + encodeURIComponent(item.id) + '/download';
        fetch(endpoint)
          .then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (data) {
              if (!response.ok || !data.url) {
                throw new Error(data.detail || '下载链接暂不可用');
              }
              return data;
            });
          })
          .then(function (data) {
            var link = document.createElement('a');
            link.href = data.url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = '下载 ' + (data.file_name || item.file_name || item.name || '文件');
            row.textContent = '';
            row.appendChild(link);
          })
          .catch(function () {
            row.textContent = (item.file_name || item.name || '文件')
              + '：下载链接暂不可用，请重新查询任务状态。';
          });
      });
    }

    function explainJob(job, artifacts) {
      var state = String(job.status || 'unknown').toLowerCase();
      var stage = job.stage ? '\n当前阶段：' + job.stage : '';
      var pct = job.progress != null && Number.isFinite(Number(job.progress))
        ? '\n进度：' + Math.round(Number(job.progress) * 100) + '%'
        : '';
      var message = '任务编号：' + job.id + '\n任务状态：' + state + stage + pct;
      if (state === 'queued') {
        message += '\n任务已排队，等待已经启动的 GPU Worker 领取。';
      } else if (state === 'running') {
        message += '\nGPU Worker 已开始处理，请稍后再次查询。';
      } else if (state === 'completed') {
        message += '\n处理已完成。已登记产物：' + ((artifacts || []).map(function (item) {
          return item.file_name || item.name || '文件';
        }).join('、') || '暂未返回文件清单');
      } else if (state === 'failed' || state === 'error') {
        message += '\n处理失败：' + (job.error || '服务端未提供详细原因');
      }
      status.textContent = message;
      if (state === 'completed') renderArtifactLinks(artifacts);
      else if (artifactsContainer) artifactsContainer.textContent = '';
      // Keep the manual action available while a queued job waits. If a worker
      // disappears after the initial check, the user can retry without re-uploading.
      start.hidden = state !== 'queued';
      start.disabled = state !== 'queued' || startRequestInFlight;
    }

    fileInput.addEventListener('change', function () {
      var file = fileInput.files && fileInput.files[0];
      filename.textContent = file
        ? file.name + ' · ' + (file.size / 1024 / 1024).toFixed(1) + ' MB'
        : '尚未选择歌曲';
    });

    submit.addEventListener('click', function () {
      var file = fileInput.files && fileInput.files[0];
      if (!file) {
        status.textContent = '请先选择一首完整歌曲。';
        fileInput.focus();
        return;
      }
      if (file.size <= 0 || file.size > 250 * 1024 * 1024) {
        status.textContent = '文件为空或超过 250 MB，请更换音频文件。';
        return;
      }
      var allowed = /\.(mp3|wav|flac|m4a|ogg)$/i;
      if (!allowed.test(file.name)) {
        status.textContent = '暂不支持这个文件格式，请使用 MP3、WAV、FLAC、M4A 或 OGG。';
        return;
      }

      var body = new FormData();
      body.append('audio', file);
      body.append('engine', 'crepe');
      body.append('key', '');
      body.append('stages', '1,2,3');
      body.append('denoise', 'dereverb');
      body.append('lyrics', lyricsInput ? lyricsInput.value : '');

      var previousJobId = activeJobId;
      if (pollTimer) clearTimeout(pollTimer);
      pollTimer = null;
      autoPoll = false;
      setBusy(true);
      refresh.hidden = true;
      start.hidden = true;
      if (artifactsContainer) artifactsContainer.textContent = '';
      status.textContent = '正在把完整歌曲上传到云端任务队列…';
      uploadFullSong(body)
        .then(function (data) {
          if (!data.job_id) throw new Error('服务器没有返回任务编号。');
          activeJobId = data.job_id;
          saveJobId(activeJobId);
          refresh.hidden = false;
          status.textContent = '完整乐曲已上传并进入云端队列。\n任务编号：' + activeJobId
            + '\n当前状态：等待开始记谱。点击下方「开始记谱」后，系统只检查并使用已经运行的 GPU。';
          start.hidden = false;
          start.disabled = false;
          autoPoll = false;
        })
        .catch(function (error) {
          status.textContent = '上传未成功：' + (error && error.message ? error.message : String(error));
          // Keep the previous task recoverable if this replacement upload fails.
          if (previousJobId) {
            activeJobId = previousJobId;
            saveJobId(previousJobId);
            refresh.hidden = false;
            queryJob(false);
          }
        })
        .finally(function () {
          setBusy(false);
        });
    });

    function queryJob(showLoading) {
      if (!activeJobId || queryInFlight) return;
      var queriedJobId = activeJobId;
      queryInFlight = true;
      refresh.disabled = true;
      if (showLoading) status.textContent = '正在查询云端任务…';
      fetch('/api/cloud/jobs/' + encodeURIComponent(queriedJobId))
        .then(function (response) {
          return response.json().catch(function () { return {}; }).then(function (data) {
            if (!response.ok) {
              var error = new Error(data.detail || data.message || ('HTTP ' + response.status));
              error.status = response.status;
              throw error;
            }
            return data;
          });
        })
        .then(function (data) {
          // A newer upload may have replaced this task while the request was in flight.
          if (queriedJobId !== activeJobId) return;
          if (!data.job) throw new Error('服务器没有返回任务详情。');
          explainJob(data.job, data.artifacts || []);
          var state = String(data.job.status || '').toLowerCase();
          if (autoPoll && (state === 'queued' || state === 'running')) {
            if (pollTimer) clearTimeout(pollTimer);
            pollTimer = setTimeout(function () { queryJob(false); }, 5000);
          } else {
            autoPoll = false;
            pollTimer = null;
          }
        })
        .catch(function (error) {
          if (queriedJobId !== activeJobId) return;
          if (error && error.status === 404) {
            activeJobId = '';
            saveJobId('');
            autoPoll = false;
            if (pollTimer) clearTimeout(pollTimer);
            pollTimer = null;
            refresh.hidden = true;
            start.hidden = true;
            status.textContent = '这条任务记录已不存在或已过期。请重新上传歌曲。';
            return;
          }
          status.textContent = '查询失败：' + (error && error.message ? error.message : String(error));
          if (autoPoll) {
            if (pollTimer) clearTimeout(pollTimer);
            pollTimer = setTimeout(function () { queryJob(false); }, 10000);
          }
        })
        .finally(function () {
          queryInFlight = false;
          refresh.disabled = false;
        });
    }

    start.addEventListener('click', function () {
      if (!activeJobId || start.disabled || startRequestInFlight) return;
      startRequestInFlight = true;
      start.disabled = true;
      status.textContent = '正在检查是否有已经运行的 GPU Worker…';
      fetch('/api/cloud/jobs/' + encodeURIComponent(activeJobId) + '/start', { method: 'POST' })
        .then(function (response) {
          return response.json().catch(function () { return {}; }).then(function (data) {
            if (!response.ok) throw new Error(data.detail || data.message || ('HTTP ' + response.status));
            return data;
          });
        })
        .then(function (data) {
          autoPoll = true;
          refresh.hidden = false;
          status.textContent = data.message || '已通知正在运行的 GPU Worker 领取任务。';
          startRequestInFlight = false;
          queryJob(false);
        })
        .catch(function (error) {
          startRequestInFlight = false;
          status.textContent = error && error.message ? error.message : String(error);
          start.disabled = false;
          start.hidden = false;
        });
    });

    refresh.addEventListener('click', function () {
      queryJob(true);
    });

    // Restore the most recent task after a page reload so the user can continue
    // checking status, retry manual start, or download completed artifacts.
    if (activeJobId) {
      refresh.hidden = false;
      status.textContent = '正在恢复上次的完整乐曲任务…';
      queryJob(false);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
