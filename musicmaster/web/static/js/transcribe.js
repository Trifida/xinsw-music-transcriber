/* 记谱(音频 → 谱)接入。
 *
 * 后端:POST /api/transcribe  字段 audio / engine('crepe'|'basic-pitch'|'bytedance') / key(可空)
 * result:{ ok, report_md, staff_svg|null, confidence_pct(0-100)|null, spots[{at,note}]|null, downloads }
 *
 * 三个产出 pane:0 解读 / 1 谱面 / 2 带走。
 * 关键:即便 result.ok===false(转录非零码失败)也要把 report_md / 错误展示出来,绝不静默。
 */
(function () {
  'use strict';

  // 安慰进度条文案:把扒谱(记谱)架构走一遍 —— 真实进度只有 ~30%(CREPE 跑)与 ~85% 两档,
  // 中间长等待靠这些技术名词 + 极慢假进度给「仍在专注工作」的安全感。
  var COMFORT_MSGS = [
    '正在用 librosa 体检录音的真实带宽与采样质量…',
    '正在加载 CREPE 深度音高跟踪模型(纯 CPU 推理)…',
    '正在逐帧估计基频 f0,时间分辨率约 10ms…',
    '正在用 Viterbi 解码把逐帧音高连成稳定音轨…',
    '正在以 pyin 作「第二只耳朵」交叉验证音高…',
    '正在比对两套估计的分歧,标出存疑片段…',
    '正在做音符切分:把连续音高聚成一个个音…',
    '正在估计每个音的起止时间与时值…',
    '正在统计音高直方图,自动推断最可能的调…',
    '正在把频率量化到十二平均律的音名…',
    '正在用 music21 构建乐谱对象模型…',
    '正在对齐节拍与小节线,规整时值…',
    '正在生成 MusicXML(可导入打谱软件)…',
    '正在调用 Verovio 渲染五线谱预览…',
    '正在折算简谱:把音名映射成 1234567…',
    '正在排版简谱的小节、附点与连音线…',
    '正在生成 LilyPond 源码以便高质量出谱…',
    '正在汇总逐音可信度,准备「想请你再听听」清单…',
    '正在打包 notes.json / MIDI / 五线谱 / 简谱…',
    '正在做最后一致性校验,确保各产物对齐…',
    '模型仍在专注工作,长录音 / 复杂旋律会更久一些…',
    '快好了 —— 正在收尾整理可下载文件…'
  ];

  function init() {
    var MM = window.MM;
    if (!MM) return;
    var panel = MM.panel('transcribe');
    if (!panel) return;

    // ── 输入:音频上传(唱机)、引擎(单选)、调(选填) ──
    var player = panel.querySelector('.card [data-player]');
    var getFile = player ? MM.makeUploadPlayer(player, 'audio/*', null) : function () { return null; };

    var btn = panel.querySelector('.cast');
    var prog = MM.progress(btn, { comfort: true, messages: COMFORT_MSGS });

    // ── 产出三 pane(按 DOM 顺序:解读 / 谱面 / 带走) ──
    var panes = panel.querySelectorAll('.out-body .out-pane');
    var paneRead = panes[0], paneSheet = panes[1], paneTake = panes[2];
    var currentJob = null;

    function onProgress(job) {
      if (job && job.stage) MM.setBusyText(btn, job.stage);
      prog.update(job);
    }

    // 解读 pane:可信度环 + 概述 + 存疑段 + 报告全文(report_md 始终展示)
    function renderRead(result) {
      if (!paneRead) return;

      // 可信度环:第二个 circle(有 stroke-dasharray="264")是进度环
      var ring = paneRead.querySelector('.ring');
      var pct = result.confidence_pct;
      if (ring && pct != null) {
        ring.style.display = '';
        var pctEl = ring.querySelector('.pct');
        if (pctEl) pctEl.textContent = String(pct);
        var arc = ring.querySelector('circle[stroke-dasharray="264"]');
        if (arc) arc.setAttribute('stroke-dashoffset', String(264 * (1 - pct / 100)));
      } else if (ring) {
        ring.style.display = 'none';
      }

      // 概述:成功一句话,软失败把 message 也带上(report_md 仍在下方完整展示)
      var gd = paneRead.querySelector('.grasp .gd');
      if (gd) {
        if (result.ok) {
          gd.textContent = pct != null
            ? ('整体把握约 ' + pct + '%。存疑处已在下方逐一标出,其余可放心。')
            : '记好了。详细解读见下方报告;存疑处(若有)已逐一标出。';
        } else {
          gd.textContent = result.message
            ? ('这一遍没能顺利记下:' + result.message + ' 详情见下方报告。')
            : '这一遍没能顺利记下,详情见下方报告。';
        }
      }

      // 存疑段:用 result.spots 重建 .spot;为空则隐藏 .listen
      var listen = paneRead.querySelector('.listen');
      if (listen) {
        var spots = result.spots;
        if (spots && spots.length) {
          listen.style.display = '';
          // 移除旧的 .spot(保留 .lh 标题),再按 spots 重建
          var olds = listen.querySelectorAll('.spot');
          for (var i = 0; i < olds.length; i++) olds[i].parentNode.removeChild(olds[i]);
          var anchor = listen.querySelector('.lh'); // 插在标题之后
          spots.forEach(function (sp) {
            var row = document.createElement('div');
            row.className = 'spot';
            row.innerHTML = '<span class="at">' + MM.esc(sp.at) + '</span>' +
                            '<span class="sw">' + MM.esc(sp.note) + '</span>';
            if (anchor && anchor.parentNode === listen) {
              anchor.parentNode.insertBefore(row, anchor.nextSibling);
              anchor = row; // 维持原始顺序
            } else {
              listen.appendChild(row);
            }
          });
        } else {
          listen.style.display = 'none';
        }
      }

      // 报告全文:始终展示(即便软失败)。复用同一个 <pre>,避免重复提交时堆叠。
      var pre = paneRead.querySelector('pre[data-report]');
      if (!pre) {
        pre = document.createElement('pre');
        pre.setAttribute('data-report', '');
        pre.style.whiteSpace = 'pre-wrap';
        paneRead.appendChild(pre);
      }
      pre.textContent = result.report_md != null ? result.report_md : '';
      pre.style.display = result.report_md != null ? '' : 'none';
    }


    function renderLyricEditor(result, sheet) {
      var slots = result.lyric_slots;
      if (!Array.isArray(slots) || !slots.length) return;

      var editor = document.createElement('section');
      editor.className = 'lyric-editor';
      editor.style.cssText = 'margin-top:24px;padding:18px;border:1px solid #ded8ce;border-radius:12px;background:#fff;color:#211e26';
      var heading = document.createElement('div');
      heading.textContent = '逐音歌词校正';
      heading.style.cssText = 'font-size:17px;font-weight:600;margin-bottom:5px';
      editor.appendChild(heading);
      var hint = document.createElement('div');
      hint.textContent = '每个格子对应一个可填歌词的旋律音符。直接改字；拖腔续音填“—”；不需要歌词的音符留空。';
      hint.style.cssText = 'font-size:12px;line-height:1.7;color:#777;margin-bottom:14px';
      editor.appendChild(hint);

      var grid = document.createElement('div');
      grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(76px,1fr));gap:8px';
      slots.forEach(function (slot, index) {
        var cell = document.createElement('label');
        cell.style.cssText = 'display:flex;flex-direction:column;gap:5px;padding:7px;border:1px solid #e5e0d8;border-radius:8px;min-width:0';
        var meta = document.createElement('span');
        meta.textContent = (index + 1) + ' · ' + (slot.pitch || '音符');
        meta.style.cssText = 'font-size:10px;color:#888;white-space:nowrap';
        var input = document.createElement('input');
        input.type = 'text';
        input.value = slot.lyric || '';
        input.maxLength = 80;
        input.setAttribute('data-lyric-slot', String(index));
        input.setAttribute('aria-label', '第 ' + (index + 1) + ' 个音符的歌词');
        input.placeholder = '空白';
        input.style.cssText = 'width:100%;min-width:0;box-sizing:border-box;padding:7px 4px;border:1px solid #d8d2c8;border-radius:6px;background:#fff;color:#211e26;font-size:14px;text-align:center';
        cell.appendChild(meta);
        cell.appendChild(input);
        grid.appendChild(cell);
      });
      editor.appendChild(grid);

      var save = document.createElement('button');
      save.type = 'button';
      save.textContent = '保存歌词修改并更新两种谱面';
      save.style.cssText = 'margin-top:14px;padding:10px 16px;border:0;border-radius:8px;background:#5b4a72;color:#fff;cursor:pointer;font-size:13px';
      save.addEventListener('click', function () {
        if (!currentJob || !currentJob.id) {
          MM.toast('找不到当前记谱任务，请重新记谱后再校正。', 'error');
          return;
        }
        var inputs = editor.querySelectorAll('input[data-lyric-slot]');
        var tokens = Array.prototype.map.call(inputs, function (input) {
          return input.value.trim() || '·';
        });
        save.disabled = true;
        save.textContent = '正在保存并重新排版…';
        fetch('/api/job/' + encodeURIComponent(currentJob.id) + '/lyrics', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(tokens)
        }).then(function (response) {
          return response.json().then(function (data) {
            if (!response.ok) throw new Error(data.detail || '歌词保存失败');
            return data;
          });
        }).then(function (data) {
          currentJob.result = data.result;
          renderSheet(data.result);
          renderTake(currentJob, data.result);
          MM.toast('歌词已保存，简谱和五线谱已更新。', 'success');
        }).catch(function (error) {
          MM.toast(error.message || String(error), 'error');
          save.disabled = false;
          save.textContent = '保存歌词修改并更新两种谱面';
        });
      });
      editor.appendChild(save);
      sheet.appendChild(editor);
    }

    // 谱面 pane:有 staff_svg 就替换 .sheet 内容
    function renderSheet(result) {
      if (!paneSheet) return;
      var sheet = paneSheet.querySelector('.sheet');
      if (!sheet) return;

      // 原版简谱是首要谱面预览；五线谱预览仍保留在同一面板下方。
      if (result.jianpu_svg) {
        var count = Number(result.jianpu_page_count) || 1;
        var html = '<div class="tt">简谱 · 原版排版</div>' +
          '<div class="st">原版 jianpu-ly + LilyPond 排版预览' + (count > 1 ? ' · 共 ' + count + ' 页' : '') + '</div>' +
          '<div class="jianpu-rendered">' + result.jianpu_svg + '</div>';
        if (result.staff_svg) {
          html += '<div class="tt" style="margin-top:28px">五线谱</div>' +
            '<div class="st">原有五线谱预览</div><div class="staff-preview">' + result.staff_svg + '</div>';
        }
        sheet.innerHTML = html;
        var jpSvgs = sheet.querySelectorAll('.jianpu-rendered svg');
        Array.prototype.forEach.call(jpSvgs, function (svg) {
          svg.style.width = '100%';
          svg.style.height = 'auto';
          svg.style.display = 'block';
          svg.style.background = '#fff';
          svg.style.marginBottom = '14px';
        });
        var staff = sheet.querySelector('.staff-preview');
        if (staff) MM.fitSheetSvg(staff);
        renderLyricEditor(result, sheet);
        return;
      }

      if (result.staff_svg) {
        sheet.innerHTML = result.staff_svg;
        MM.fitSheetSvg(sheet);
      }
      renderLyricEditor(result, sheet);
    }

    // 带走 pane:下载网格
    function renderTake(job, result) {
      if (!paneTake) return;
      var grid = paneTake.querySelector('.dl-grid');
      MM.renderDownloads(grid, job.id, result.downloads || []);
    }

    function onResult(job) {
      currentJob = job;
      // 硬失败:任务执行出错(无 result)
      if (job.status === 'error') {
        MM.toast(job.error || '记谱任务出错了。', 'error');
        return;
      }
      var result = job.result || {};

      // 软失败且无报告(如引擎环境未就绪):仅有 message,展示并切到解读 pane
      if (result.ok === false && result.report_md == null) {
        MM.toast(result.message || '记谱未能完成。', 'error');
        renderRead(result); // 隐藏环/存疑、概述显示 message
        MM.switchOut(panel, 0);
        return;
      }

      // 其余两种:ok===true 正常渲染,或 ok===false 但带 report_md(转录非零码失败)
      // —— 两者都要完整展示报告/谱面/产物,不静默。
      if (result.ok === false) {
        MM.toast(result.message || '记谱以失败收场,但已保留报告与可印源稿。', 'error');
      }
      renderRead(result);
      renderSheet(result);
      renderTake(job, result);
      MM.switchOut(panel, 0);
    }

    if (btn) {
      btn.addEventListener('click', function () {
        var file = getFile();
        if (!file) { MM.toast('请先点唱机选一段歌声音频。', 'error'); return; }

        var engineEl = panel.querySelector('input[name=tr]:checked');
        var engine = engineEl ? engineEl.value : 'crepe';
        var keyEl = panel.querySelector('.input');
        var key = keyEl ? keyEl.value.trim() : '';

        var fd = new FormData();
        fd.append('audio', file);
        fd.append('engine', engine);
        fd.append('key', key);
        var lyricsEl = panel.querySelector('.lyric-input');
        var autoLyricsEl = panel.querySelector('.auto-lyrics');
        fd.append('lyrics', lyricsEl ? lyricsEl.value : '');
        fd.append('auto_lyrics', autoLyricsEl && autoLyricsEl.checked ? 'true' : 'false');

        var restore = MM.setBusy(btn, '提交中…');
        prog.start();
        MM.run('transcribe', fd, onProgress)
          .then(function (job) {
            var ok = job.status !== 'error' && job.result && job.result.ok;
            if (ok) prog.done(); else prog.fail();
            onResult(job);
          })
          .catch(function (e) { prog.fail(); MM.toast('' + e, 'error'); })
          .finally(restore);
      });
    }

    MM.clearButton(panel, function () {
      if (getFile.clear) getFile.clear();
      var lyricsEl = panel.querySelector('.lyric-input');
      var autoLyricsEl = panel.querySelector('.auto-lyrics');
      if (lyricsEl) lyricsEl.value = '';
      if (autoLyricsEl) autoLyricsEl.checked = false;
      if (btn && btn._mmProg) btn._mmProg.hide();
      if (paneTake) MM.renderDownloads(paneTake.querySelector('.dl-grid'), '', []);
      var au = panel.querySelectorAll('audio');
      Array.prototype.forEach.call(au, function (a) { try { a.pause(); } catch (e) {} });
      MM.switchOut(panel, 0);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
