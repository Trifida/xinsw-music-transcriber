/* Full-song upload entry for the transcription panel.
 * This submits the original mixed recording to the durable cloud-job API.
 * It does not claim that a GPU worker has started: automatic dispatch is a
 * separate unfinished capability and the UI says so explicitly.
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
    if (!fileInput || !submit || !status || !refresh) return;

    var activeJobId = '';

    function setBusy(busy) {
      submit.disabled = busy;
      submit.style.opacity = busy ? '.65' : '';
      submit.style.pointerEvents = busy ? 'none' : '';
      submit.setAttribute('aria-busy', busy ? 'true' : 'false');
    }

    function explainJob(job, artifacts) {
      var state = String(job.status || 'unknown').toLowerCase();
      var stage = job.stage ? '\n当前阶段：' + job.stage : '';
      var pct = Number.isFinite(Number(job.progress))
        ? '\n进度：' + Math.round(Number(job.progress) * 100) + '%'
        : '';
      var message = '任务编号：' + job.id + '\n任务状态：' + state + stage + pct;
      if (state === 'queued') {
        message += '\n任务已进入云端队列。当前自动 GPU 调度尚未启用，任务不会自行开始处理。';
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

      setBusy(true);
      refresh.hidden = true;
      status.textContent = '正在把完整歌曲上传到云端任务队列…';
      fetch('/api/cloud/jobs', { method: 'POST', body: body })
        .then(function (response) {
          return response.json().catch(function () { return {}; }).then(function (data) {
            if (!response.ok) {
              throw new Error(data.detail || data.message || ('HTTP ' + response.status));
            }
            return data;
          });
        })
        .then(function (data) {
          if (!data.job_id) throw new Error('服务器没有返回任务编号。');
          activeJobId = data.job_id;
          refresh.hidden = false;
          status.textContent = '完整歌曲已上传并进入云端队列。\n任务编号：' + activeJobId
            + '\n当前状态：' + (data.status || 'queued')
            + '\n注意：GPU 自动调度尚未启用，本次上传只完成入队，不代表已经开始扒谱。';
        })
        .catch(function (error) {
          status.textContent = '上传未成功：' + (error && error.message ? error.message : String(error));
        })
        .finally(function () {
          setBusy(false);
        });
    });

    refresh.addEventListener('click', function () {
      if (!activeJobId) return;
      refresh.disabled = true;
      status.textContent = '正在查询云端任务…';
      fetch('/api/cloud/jobs/' + encodeURIComponent(activeJobId))
        .then(function (response) {
          return response.json().catch(function () { return {}; }).then(function (data) {
            if (!response.ok) {
              throw new Error(data.detail || data.message || ('HTTP ' + response.status));
            }
            return data;
          });
        })
        .then(function (data) {
          if (!data.job) throw new Error('服务器没有返回任务详情。');
          explainJob(data.job, data.artifacts || []);
        })
        .catch(function (error) {
          status.textContent = '查询失败：' + (error && error.message ? error.message : String(error));
        })
        .finally(function () {
          refresh.disabled = false;
        });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
