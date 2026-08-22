const { entrypoints } = require("uxp");

let uxpApi = null;
let premiereApi = null;
let connectedUrl = "";
let generating = false;
let pendingSegments = [];
let initialized = false;
let domReadyBound = false;
let nextId = 1;
let results = [];
let playingId = null;
let previewTimer = null;
let previewHelperFile = null;
let previewRequestToken = 0;
let outputFolderEntry = null;
let outputFolderPath = "";

const API_URLS = ["http://127.0.0.1:9880", "http://localhost:9880"];
const PREVIEW_API_URL = "http://127.0.0.1:39881";
const OUTPUT_FOLDER_STORAGE_KEY = "mambotts.outputFolderPath";

function getPremiereApi() {
  if (!premiereApi) premiereApi = require("premierepro");
  return premiereApi;
}

function getUxpApi() {
  if (!uxpApi) uxpApi = require("uxp");
  return uxpApi;
}

function element(id) {
  return document.getElementById(id);
}

function errorText(error) {
  return error && error.message ? error.message : String(error);
}

function nativePathToFileUrl(nativePath) {
  let normalized = String(nativePath || "").replace(/\\/g, "/");
  if (normalized.charAt(0) !== "/") normalized = "/" + normalized;
  return "file://" + encodeURI(normalized);
}

function readStoredOutputFolderPath() {
  try {
    return typeof localStorage === "undefined" ? "" : localStorage.getItem(OUTPUT_FOLDER_STORAGE_KEY) || "";
  } catch (_) {
    return "";
  }
}

function writeStoredOutputFolderPath(nativePath) {
  try {
    if (typeof localStorage !== "undefined") localStorage.setItem(OUTPUT_FOLDER_STORAGE_KEY, nativePath);
  } catch (_) {}
}

function renderOutputLocation() {
  const label = element("outputLocation");
  if (!label) return;
  if (!outputFolderPath) {
    label.textContent = "默认位置";
    label.title = "默认保存到插件数据目录";
    return;
  }
  const normalized = outputFolderPath.replace(/\\/g, "/").replace(/\/$/, "");
  label.textContent = normalized.slice(normalized.lastIndexOf("/") + 1) || normalized;
  label.title = outputFolderPath;
}

function setRefreshBusy(busy) {
  const refresh = element("refreshEngine");
  if (!refresh) return;
  refresh.setAttribute("aria-disabled", busy ? "true" : "false");
  refresh.style.pointerEvents = busy ? "none" : "auto";
  refresh.style.opacity = busy ? "0.55" : "1";
}

function requestWithTimeout(url, options, timeoutMs) {
  return new Promise(function (resolve, reject) {
    const timer = setTimeout(function () {
      reject(new Error("连接超时"));
    }, timeoutMs);

    fetch(url, options || {}).then(function (response) {
      clearTimeout(timer);
      resolve(response);
    }, function (error) {
      clearTimeout(timer);
      reject(error);
    });
  });
}

function setEngineState(state) {
  const text = element("engineText");
  if (!text) return;

  if (state === "online") {
    text.textContent = "引擎在线中";
    text.style.color = "#58b867";
  } else if (state === "offline") {
    text.textContent = "引擎未连接";
    text.style.color = "#e06c67";
  } else {
    text.textContent = "引擎检测中";
    text.style.color = "#d5a758";
  }
}

function appendLog(containerId, message, type) {
  const container = element(containerId);
  if (!container) return;

  if (container.getAttribute("data-empty") !== "false") {
    container.textContent = "";
    container.setAttribute("data-empty", "false");
  }

  const entry = document.createElement("div");
  entry.textContent = message;
  entry.style.margin = "0 0 2px";
  entry.style.overflowWrap = "anywhere";
  entry.style.color = type === "success" ? "#58b867" : type === "error" ? "#e06c67" : "#bdbdbd";
  container.appendChild(entry);

  while (container.children.length > 120) {
    container.removeChild(container.firstElementChild);
  }
  container.scrollTop = container.scrollHeight;
}

async function checkEngine(reportFailure) {
  setEngineState("checking");
  setRefreshBusy(true);
  const failures = [];

  for (let index = 0; index < API_URLS.length; index += 1) {
    const baseUrl = API_URLS[index];
    try {
      const response = await requestWithTimeout(baseUrl + "/control", { method: "GET" }, 4000);
      // A reachable engine may answer /control with 200, 404, or 405 depending
      // on the MamboTTS build. Any HTTP response proves the local service is up.
      if (response && typeof response.status === "number") {
        connectedUrl = baseUrl;
        setEngineState("online");
        setRefreshBusy(false);
        return true;
      }
      failures.push("HTTP " + response.status);
    } catch (error) {
      failures.push(errorText(error));
    }
  }

  connectedUrl = "";
  setEngineState("offline");
  setRefreshBusy(false);
  if (reportFailure !== false) {
    const detail = failures.filter(function (value, index, all) {
      return all.indexOf(value) === index;
    }).join("；") || "请求失败";
    appendLog("generationLog", "引擎连接失败：" + detail + "。请先手动启动 MamboTTS。", "error");
  }
  return false;
}

function splitSegments(text) {
  const normalized = String(text || "").replace(/\r\n/g, "\n").trim();
  if (!normalized) return [];
  const parts = /\n\s*\n/.test(normalized)
    ? normalized.split(/\n\s*\n+/)
    : normalized.split(/\n+/);
  return parts.map(function (part) {
    return part.trim();
  }).filter(function (part) {
    return Boolean(part);
  });
}

function previewText(text, length) {
  const limit = typeof length === "number" ? length : 22;
  const oneLine = String(text || "").replace(/\s+/g, " ").trim();
  return oneLine.length > limit ? oneLine.slice(0, limit) + "..." : oneLine;
}

function padNumber(value) {
  return String(value).padStart(2, "0");
}

function makeFileName(text, id) {
  const now = new Date();
  const stamp = now.getFullYear() + padNumber(now.getMonth() + 1) + padNumber(now.getDate()) + "_" +
    padNumber(now.getHours()) + padNumber(now.getMinutes()) + padNumber(now.getSeconds());
  const name = String(text || "")
    .slice(0, 16)
    .replace(/[^\w\u4e00-\u9fff]+/g, "-")
    .replace(/^-|-$/g, "") || "mambo";
  return "Mambo_" + name + "_" + stamp + "_" + id + ".wav";
}

async function getOutputFolder() {
  if (outputFolderEntry) return outputFolderEntry;

  if (!outputFolderPath) {
    outputFolderPath = readStoredOutputFolderPath();
  }

  const fileSystem = getUxpApi().storage.localFileSystem;
  if (outputFolderPath) {
    try {
      const savedFolder = await fileSystem.getEntryWithUrl(nativePathToFileUrl(outputFolderPath));
      if (savedFolder && savedFolder.nativePath) {
        outputFolderEntry = savedFolder;
        outputFolderPath = savedFolder.nativePath;
        renderOutputLocation();
        return outputFolderEntry;
      }
    } catch (_) {
      outputFolderEntry = null;
    }
  }

  const dataFolder = await fileSystem.getDataFolder();
  try {
    outputFolderEntry = await dataFolder.getEntry("output");
  } catch (_) {
    outputFolderEntry = await dataFolder.createFolder("output");
  }
  outputFolderPath = "";
  renderOutputLocation();
  return outputFolderEntry;
}

async function chooseOutputFolder() {
  const control = element("outputLocation");
  if (control) {
    control.setAttribute("aria-disabled", "true");
    control.style.pointerEvents = "none";
    control.style.opacity = "0.55";
  }
  try {
    const folder = await getUxpApi().storage.localFileSystem.getFolder();
    if (!folder || !folder.nativePath) return;
    outputFolderEntry = folder;
    outputFolderPath = folder.nativePath;
    writeStoredOutputFolderPath(outputFolderPath);
    renderOutputLocation();
  } catch (error) {
    appendLog("generationLog", "输出位置选择失败：" + errorText(error), "error");
  } finally {
    if (control) {
      control.setAttribute("aria-disabled", "false");
      control.style.pointerEvents = "auto";
      control.style.opacity = "1";
    }
  }
}

async function loadOutputFolderSetting() {
  outputFolderPath = readStoredOutputFolderPath();
  renderOutputLocation();
  if (!outputFolderPath) return;
  try {
    await getOutputFolder();
  } catch (_) {
    outputFolderEntry = null;
    outputFolderPath = "";
    renderOutputLocation();
  }
}

function readAscii(bytes, offset, length) {
  let value = "";
  for (let index = 0; index < length && offset + index < bytes.length; index += 1) {
    value += String.fromCharCode(bytes[offset + index]);
  }
  return value;
}

function getWavDurationSeconds(buffer) {
  try {
    const bytes = new Uint8Array(buffer);
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    if (readAscii(bytes, 0, 4) !== "RIFF" || readAscii(bytes, 8, 4) !== "WAVE") return 0;
    let offset = 12;
    let byteRate = 0;
    let dataSize = 0;
    while (offset + 8 <= bytes.length) {
      const chunkId = readAscii(bytes, offset, 4);
      const chunkSize = view.getUint32(offset + 4, true);
      const chunkData = offset + 8;
      if (chunkId === "fmt " && chunkSize >= 16 && chunkData + 16 <= bytes.length) {
        byteRate = view.getUint32(chunkData + 8, true);
      } else if (chunkId === "data") {
        dataSize = chunkSize;
        break;
      }
      offset = chunkData + chunkSize + (chunkSize % 2);
    }
    return byteRate > 0 && dataSize > 0 ? dataSize / byteRate : 0;
  } catch (_) {
    return 0;
  }
}

function createActionButton(label, title, color, handler, disabled) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.title = title;
  button.setAttribute("aria-label", title);
  button.disabled = Boolean(disabled);
  button.style.boxSizing = "border-box";
  button.style.flex = "0 0 23px";
  button.style.width = "23px";
  button.style.height = "23px";
  button.style.margin = "0 0 0 2px";
  button.style.padding = "0";
  button.style.border = "1px solid transparent";
  button.style.borderRadius = "2px";
  button.style.background = "transparent";
  button.style.color = color;
  button.style.font = "600 14px 'Segoe UI Symbol','Segoe UI',sans-serif";
  button.addEventListener("click", handler);
  return button;
}

function renderResults() {
  const list = element("resultList");
  const empty = element("emptyResults");
  if (!list || !empty) return;

  list.textContent = "";
  empty.style.display = results.length ? "none" : "block";

  results.forEach(function (item) {
    const row = document.createElement("div");
    row.style.boxSizing = "border-box";
    row.style.display = "flex";
    row.style.alignItems = "center";
    row.style.width = "100%";
    row.style.minHeight = "34px";
    row.style.padding = "4px 4px 4px 6px";
    row.style.borderBottom = "1px solid #3a3a3a";
    row.style.background = playingId === item.id ? "#263229" : "transparent";

    const duration = document.createElement("span");
    duration.textContent = "[" + (typeof item.durationSeconds === "number" ? item.durationSeconds.toFixed(1) : "0.0") + "s]";
    duration.style.flex = "0 0 37px";
    duration.style.width = "37px";
    duration.style.color = "#888";
    duration.style.font = "11px 'Segoe UI',sans-serif";

    const text = document.createElement("div");
    text.textContent = item.text;
    text.title = item.text;
    text.style.flex = "1";
    text.style.minWidth = "0";
    text.style.maxHeight = "32px";
    text.style.overflow = "hidden";
    text.style.color = "#d4d4d4";
    text.style.lineHeight = "16px";
    text.style.overflowWrap = "anywhere";

    row.appendChild(duration);
    row.appendChild(text);
    row.appendChild(createActionButton("▶", "播放", "#b7b7b7", function () {
      playResult(item);
    }, item.busy));
    row.appendChild(createActionButton("+", "插入当前所选音轨", "#b7b7b7", function () {
      insertResult(item);
    }, item.busy));
    row.appendChild(createActionButton("×", "从列表删除", "#c7a09d", function () {
      removeResult(item.id);
    }, item.busy));
    list.appendChild(row);
  });
}

function clearPreviewState() {
  if (previewTimer) {
    clearTimeout(previewTimer);
    previewTimer = null;
  }
  playingId = null;
  renderResults();
}

async function getPreviewHelperFile() {
  if (previewHelperFile) return previewHelperFile;
  const pluginFolder = await getUxpApi().storage.localFileSystem.getPluginFolder();
  try {
    previewHelperFile = await pluginFolder.getEntry("MamboTTSPreview.exe");
  } catch (_) {
    throw new Error("后台试听组件缺失，请退出 Premiere 后重新运行 install.ps1");
  }
  return previewHelperFile;
}

async function requestPreview(path, options, timeoutMs) {
  const response = await requestWithTimeout(PREVIEW_API_URL + path, options || {}, timeoutMs);
  if (!response.ok) {
    let detail = "HTTP " + response.status;
    try {
      const message = await response.text();
      if (message) detail += "：" + message;
    } catch (_) {}
    throw new Error(detail);
  }
  return response;
}

async function launchPreviewHelper() {
  const helper = await getPreviewHelperFile();
  const shell = getUxpApi().shell;
  if (!shell || typeof shell.openPath !== "function") {
    throw new Error("当前 UXP 环境不支持启动后台试听组件");
  }
  const launchError = await shell.openPath(helper.nativePath, "在后台试听生成的配音");
  if (launchError) throw new Error(launchError);

  for (let attempt = 0; attempt < 30; attempt += 1) {
    await new Promise(function (resolve) {
      setTimeout(resolve, 100);
    });
    try {
      await requestPreview("/health", { method: "GET" }, 400);
      return;
    } catch (_) {}
  }
  throw new Error("Rust 后台试听组件启动失败");
}

async function sendPreviewCommand(command, filePath) {
  const path = command === "play" ? "/play" : "/stop";
  const options = {
    method: "POST",
    headers: { "Content-Type": "text/plain; charset=utf-8" },
    body: filePath || ""
  };

  if (command === "stop") {
    try {
      await requestPreview(path, options, 600);
    } catch (_) {}
    return;
  }

  try {
    await requestPreview(path, options, 700);
    return;
  } catch (_) {}

  await launchPreviewHelper();
  await requestPreview(path, options, 2000);
}

async function stopMediaPreview(signalHelper) {
  previewRequestToken += 1;
  clearPreviewState();
  if (signalHelper) await sendPreviewCommand("stop", "");
}

async function playResult(item) {
  if (item.busy) return;
  let requestToken = 0;

  try {
    if (playingId === item.id) {
      await stopMediaPreview(true);
      return;
    }
    clearPreviewState();
    requestToken = previewRequestToken + 1;
    previewRequestToken = requestToken;
    await sendPreviewCommand("play", item.filePath);
    if (requestToken !== previewRequestToken) return;

    playingId = item.id;
    renderResults();
    const durationMs = Math.max(250, Math.ceil((item.durationSeconds || 0) * 1000) + 150);
    previewTimer = setTimeout(function () {
      if (requestToken === previewRequestToken) clearPreviewState();
    }, durationMs);
  } catch (error) {
    if (requestToken && requestToken !== previewRequestToken) return;
    clearPreviewState();
    appendLog("insertLog", "播放失败：" + errorText(error), "error");
  }
}

async function removeResult(id) {
  const item = results.find(function (entry) {
    return entry.id === id;
  });
  if (!item || item.busy) return;

  if (playingId === id) {
    await stopMediaPreview(true);
  }

  item.busy = true;
  renderResults();
  try {
    await removeImportedAsset(item);
    results = results.filter(function (entry) {
      return entry.id !== id;
    });
    renderResults();
  } catch (error) {
    appendLog("insertLog", "删除失败：" + errorText(error), "error");
    item.busy = false;
    renderResults();
  }
}

async function synthesize(text) {
  const id = nextId;
  nextId += 1;
  const shortText = "“" + previewText(text, 22) + "”";
  appendLog("generationLog", shortText + " 生成中", "info");

  try {
    const response = await requestWithTimeout(connectedUrl + "/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: text,
        text_language: "zh",
        speed: 1,
        cut_punc: "，。？！；：、…,.;?!"
      })
    }, 120000);

    const contentType = response.headers.get("content-type") || "";
    if (!response.ok || (contentType && contentType.indexOf("audio") === -1)) {
      let detail = "";
      try {
        detail = (await response.text()).slice(0, 300);
      } catch (_) {}
      throw new Error("HTTP " + response.status + (detail ? "：" + detail : ""));
    }

    const buffer = await response.arrayBuffer();
    if (buffer.byteLength < 44) throw new Error("引擎返回的音频为空");

    const folder = await getOutputFolder();
    const fileName = makeFileName(text, id);
    const file = await folder.createFile(fileName, { overwrite: true });
    await file.write(buffer, { format: getUxpApi().storage.formats.binary });

    results.push({
      id: id,
      text: text,
      fileName: fileName,
      filePath: file.nativePath,
      durationSeconds: getWavDurationSeconds(buffer),
      busy: false
    });
    renderResults();
    appendLog("generationLog", shortText + " 生成完毕", "success");
  } catch (error) {
    appendLog("generationLog", shortText + " 生成错误：" + errorText(error), "error");
  }
}

async function processGenerationQueue() {
  if (generating || !pendingSegments.length) return;
  generating = true;
  try {
    if (!connectedUrl && !(await checkEngine(true))) return;
    while (pendingSegments.length) {
      await synthesize(pendingSegments.shift());
    }
  } finally {
    generating = false;
  }
}

function generateSegments() {
  const script = element("script");
  const segments = splitSegments(script ? script.value : "");
  if (!segments.length) {
    appendLog("generationLog", "请输入配音文本", "error");
    if (script) script.focus();
    return;
  }

  pendingSegments = pendingSegments.concat(segments);
  if (script) {
    script.value = "";
    script.focus();
  }
  processGenerationQueue().catch(function (error) {
    appendLog("generationLog", "生成队列错误：" + errorText(error), "error");
  });
}

async function getActiveProjectAndSequence() {
  const project = await getPremiereApi().Project.getActiveProject();
  if (!project) throw new Error("请先打开 Premiere 项目");
  const sequence = await project.getActiveSequence();
  if (!sequence) throw new Error("请先打开一个时间轴序列");
  return { project: project, sequence: sequence };
}

function guidString(value) {
  try {
    return value && typeof value.toString === "function" ? value.toString() : String(value || "");
  } catch (_) {
    return "";
  }
}

async function selectedItemBelongsToAudioTrack(sequence, selectedItem, trackIndex) {
  const audioTrack = await sequence.getAudioTrack(trackIndex);
  try {
    const selectedMediaType = guidString(await selectedItem.getMediaType());
    const audioMediaType = guidString(await audioTrack.getMediaType());
    if (selectedMediaType && audioMediaType) return selectedMediaType === audioMediaType;
  } catch (_) {}

  try {
    const audioItems = await audioTrack.getTrackItems(getPremiereApi().Constants.TrackItemType.CLIP, false);
    for (let index = 0; index < audioItems.length; index += 1) {
      if (audioItems[index] === selectedItem) return true;
    }

    const selectedSignature = await trackItemSignature(selectedItem);
    for (let index = 0; index < audioItems.length; index += 1) {
      if (await trackItemSignature(audioItems[index]) === selectedSignature) return true;
    }
  } catch (_) {}
  return false;
}

async function trackItemSignature(item) {
  const projectItem = await item.getProjectItem();
  let projectId = "";
  try {
    projectId = guidString(getPremiereApi().UniqueSerializeable.cast(projectItem).getUniqueID());
  } catch (_) {
    projectId = projectItem && projectItem.name ? projectItem.name : "";
  }
  const start = await item.getStartTime();
  const end = await item.getEndTime();
  let name = "";
  try {
    name = typeof item.getName === "function" ? await item.getName() : "";
  } catch (_) {}
  return [projectId, start && start.ticks, end && end.ticks, name].join("|");
}

async function getSelectedAudioTrackIndex(sequence) {
  const selection = await sequence.getSelection();
  const selectedItems = selection ? await selection.getTrackItems() : [];
  const audioTrackCount = await sequence.getAudioTrackCount();

  for (let index = 0; index < selectedItems.length; index += 1) {
    const selectedItem = selectedItems[index];
    let trackIndex = -1;
    try {
      trackIndex = await selectedItem.getTrackIndex();
    } catch (_) {
      continue;
    }
    if (trackIndex < 0 || trackIndex >= audioTrackCount) continue;
    if (await selectedItemBelongsToAudioTrack(sequence, selectedItem, trackIndex)) return trackIndex;
  }
  throw new Error("请先在时间轴中选择一个音频剪辑以指定目标音轨");
}

function normalizePath(filePath) {
  return String(filePath || "").replace(/\\/g, "/").toLowerCase();
}

function asClip(projectItem) {
  try {
    return getPremiereApi().ClipProjectItem.cast(projectItem) || projectItem;
  } catch (_) {
    return projectItem;
  }
}

async function findImportedClip(root, filePath) {
  const wanted = normalizePath(filePath);
  const items = await root.getItems();
  for (let index = 0; index < items.length; index += 1) {
    const clip = asClip(items[index]);
    try {
      if (normalizePath(await clip.getMediaFilePath()) === wanted) return clip;
    } catch (_) {}
  }
  return null;
}

async function getMamboFolder(project) {
  const premiere = getPremiereApi();
  const root = await project.getRootItem();
  const folderNames = ["Mambo TTS", "Mambo TTS"];
  const items = await root.getItems();
  for (let index = 0; index < items.length; index += 1) {
    const projectItem = items[index];
    if (projectItem && folderNames.indexOf(projectItem.name) !== -1 &&
      (projectItem.type === premiere.ProjectItem.TYPE_BIN || projectItem.type === undefined)) {
      return premiere.FolderItem.cast(projectItem);
    }
  }

  let created = false;
  project.lockedAccess(function () {
    created = project.executeTransaction(function (compoundAction) {
      compoundAction.addAction(root.createBinAction(folderNames[0], false));
      return true;
    }, "创建 Mambo TTS 文件夹");
  });
  if (created === false) throw new Error("无法创建 Mambo TTS 文件夹");

  const refreshedItems = await root.getItems();
  for (let index = 0; index < refreshedItems.length; index += 1) {
    const projectItem = refreshedItems[index];
    if (projectItem && folderNames.indexOf(projectItem.name) !== -1) {
      return premiere.FolderItem.cast(projectItem);
    }
  }
  throw new Error("Mambo TTS 文件夹创建后无法定位");
}

function asProjectItem(projectItem) {
  try {
    return getPremiereApi().ProjectItem.cast(projectItem) || projectItem;
  } catch (_) {
    return projectItem;
  }
}

async function importResult(project, item) {
  const bin = await getMamboFolder(project);
  let clip = await findImportedClip(bin, item.filePath);
  if (clip) {
    return { clip: clip, projectItem: asProjectItem(clip), bin: bin };
  }

  const imported = await project.importFiles([item.filePath], true, asProjectItem(bin), false);
  if (!imported) throw new Error("无法导入生成的音频");

  for (let attempt = 0; attempt < 6; attempt += 1) {
    clip = await findImportedClip(bin, item.filePath);
    if (clip) {
      return { clip: clip, projectItem: asProjectItem(clip), bin: bin };
    }
    await new Promise(function (resolve) {
      setTimeout(resolve, 120);
    });
  }
  throw new Error("音频已导入，但无法在项目中定位");
}

async function removeImportedAsset(item) {
  if (item.projectItem && item.projectBin) {
    const project = await item.projectItem.getProject();
    let removed = false;
    project.lockedAccess(function () {
      removed = project.executeTransaction(function (compoundAction) {
        compoundAction.addAction(item.projectBin.createRemoveItemAction(item.projectItem));
        return true;
      }, "删除 Mambo TTS 素材");
    });
    if (removed === false) throw new Error("Premiere 未能删除项目素材");
    item.projectItem = null;
    item.projectBin = null;
  }

  if (item.filePath) {
    try {
      const file = await getUxpApi().storage.localFileSystem.getEntryWithUrl(nativePathToFileUrl(item.filePath));
      if (file && typeof file.delete === "function") await file.delete();
    } catch (_) {
      // A missing generated file is already equivalent to a deleted result.
    }
  }
}

async function insertResult(item) {
  if (item.busy) return;
  item.busy = true;
  renderResults();

  try {
    const context = await getActiveProjectAndSequence();
    const project = context.project;
    const sequence = context.sequence;
    const audioTrackIndex = await getSelectedAudioTrackIndex(sequence);
    let sourceMonitorItem = null;
    try {
      sourceMonitorItem = await getPremiereApi().SourceMonitor.getProjectItem();
    } catch (_) {}
    const imported = await importResult(project, item);
    const projectItem = imported.projectItem;
    item.projectItem = projectItem;
    item.projectBin = imported.bin;
    const playhead = await sequence.getPlayerPosition();
    const editor = getPremiereApi().SequenceEditor.getEditor(sequence);
    let transactionResult = false;

    project.lockedAccess(function () {
      transactionResult = project.executeTransaction(function (compoundAction) {
        compoundAction.addAction(editor.createOverwriteItemAction(projectItem, playhead, -1, audioTrackIndex));
        return true;
      }, "插入 " + item.fileName);
    });

    if (transactionResult === false) throw new Error("Premiere 未能完成时间轴编辑");
    if (sourceMonitorItem) {
      try {
        await getPremiereApi().SourceMonitor.openProjectItem(sourceMonitorItem);
      } catch (_) {}
    } else {
      try {
        await getPremiereApi().SourceMonitor.closeClip();
      } catch (_) {}
    }
    appendLog("insertLog", "插入所选音轨成功：" + previewText(item.text, 30), "success");
  } catch (error) {
    appendLog("insertLog", "插入失败：" + errorText(error), "error");
  } finally {
    item.busy = false;
    renderResults();
  }
}

function bindEvents() {
  const refresh = element("refreshEngine");
  refresh.addEventListener("click", function () {
    checkEngine(true).then(function (online) {
      if (online) processGenerationQueue();
    });
  });
  refresh.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      checkEngine(true).then(function (online) {
        if (online) processGenerationQueue();
      });
    }
  });
  element("generate").addEventListener("click", generateSegments);
  const outputLocation = element("outputLocation");
  outputLocation.addEventListener("click", chooseOutputFolder);
  outputLocation.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      chooseOutputFolder();
    }
  });
}

function initializePanel() {
  if (initialized) return;
  if (!element("engineText") || !element("generate") || !element("resultList") ||
    !element("outputLocation")) {
    if (!domReadyBound) {
      domReadyBound = true;
      document.addEventListener("DOMContentLoaded", initializePanel);
    }
    return;
  }

  initialized = true;
  bindEvents();
  loadOutputFolderSetting().catch(function (error) {
    appendLog("generationLog", "输出位置初始化失败：" + errorText(error), "error");
  });
  renderResults();
  checkEngine(true).catch(function (error) {
    setEngineState("offline");
    appendLog("generationLog", "插件初始化失败：" + errorText(error), "error");
  });
}

entrypoints.setup({
  panels: {
    mamboTtsPanel: {
      show() {
        initializePanel();
      },
      hide() {}
    }
  }
});

if (document.readyState === "loading") {
  domReadyBound = true;
  document.addEventListener("DOMContentLoaded", initializePanel);
} else {
  initializePanel();
}
