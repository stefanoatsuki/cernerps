var SEVERITY_SCORES = {"Critical": 0, "Significant": 0.33, "Minor": 0.67, "None": 1};

var RAW_COLS = [
  "timestamp", "documentId", "noteType", "readerSpecialty", "evaluator", "group",
  "m1_hall_fab", "m1_hall_fab_f", "m1_hall_inf", "m1_inf_breakdown", "m1_hall_inf_f",
  "m1_omission", "m1_omission_f", "m1_omission_sev",
  "m1_extraneous", "m1_extraneous_f", "m1_extraneous_sev",
  "m1_flow", "m1_flow_f",
  "m2_hall_fab", "m2_hall_fab_f", "m2_hall_inf", "m2_inf_breakdown", "m2_hall_inf_f",
  "m2_omission", "m2_omission_f", "m2_omission_sev",
  "m2_extraneous", "m2_extraneous_f", "m2_extraneous_sev",
  "m2_flow", "m2_flow_f",
  "m3_hall_fab", "m3_hall_fab_f", "m3_hall_inf", "m3_inf_breakdown", "m3_hall_inf_f",
  "m3_omission", "m3_omission_f", "m3_omission_sev",
  "m3_extraneous", "m3_extraneous_f", "m3_extraneous_sev",
  "m3_flow", "m3_flow_f",
  "preference", "pref_reasons"
];

var SCORE_COLS = [
  "m1_fab_score", "m1_inf_score", "m1_omission_score", "m1_extraneous_score", "m1_flow_score",
  "m2_fab_score", "m2_inf_score", "m2_omission_score", "m2_extraneous_score", "m2_flow_score",
  "m3_fab_score", "m3_inf_score", "m3_omission_score", "m3_extraneous_score", "m3_flow_score"
];

function scoreModel(data, prefix) {
  var scores = [];
  scores.push(data[prefix + "hall_fab"] === "No hallucination" ? 1 : 0);
  if (data[prefix + "hall_inf"] === "No clinical inference") {
    scores.push(1);
  } else if (data[prefix + "inf_breakdown"] === "Unsafe, NON-Deducible Inference") {
    scores.push(0);
  } else {
    scores.push(1);
  }
  if (data[prefix + "omission"] === "No omission") {
    scores.push(1);
  } else {
    var omSev = data[prefix + "omission_sev"] || "";
    scores.push(SEVERITY_SCORES[omSev] !== undefined ? SEVERITY_SCORES[omSev] : 0);
  }
  if (data[prefix + "extraneous"] === "No extraneous information") {
    scores.push(1);
  } else {
    var exSev = data[prefix + "extraneous_sev"] || "";
    scores.push(SEVERITY_SCORES[exSev] !== undefined ? SEVERITY_SCORES[exSev] : 0);
  }
  scores.push(data[prefix + "flow"] === "No flow issues" ? 1 : 0);
  return scores;
}

function doPost(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var data = JSON.parse(e.postData.contents);
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(RAW_COLS.concat(SCORE_COLS));
  }
  var row = [new Date().toISOString()];
  for (var i = 1; i < RAW_COLS.length; i++) {
    row.push(data[RAW_COLS[i]] || "");
  }
  var scores = scoreModel(data, "m1_")
    .concat(scoreModel(data, "m2_"))
    .concat(scoreModel(data, "m3_"));
  row = row.concat(scores);
  sheet.appendRow(row);
  return ContentService.createTextOutput(JSON.stringify({status: "ok"}))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var data = sheet.getDataRange().getValues();
  if (data.length <= 1) {
    return ContentService.createTextOutput("[]")
      .setMimeType(ContentService.MimeType.JSON);
  }
  var headers = data[0];
  var rows = [];
  for (var i = 1; i < data.length; i++) {
    var obj = {};
    for (var j = 0; j < headers.length; j++) {
      obj[headers[j]] = data[i][j];
    }
    rows.push(obj);
  }
  return ContentService.createTextOutput(JSON.stringify(rows))
    .setMimeType(ContentService.MimeType.JSON);
}
