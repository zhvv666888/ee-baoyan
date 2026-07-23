const form = document.getElementById('profile-form');
const results = document.getElementById('results');
const summary = document.getElementById('summary');
const notice = document.getElementById('notice');
const submitBtn = document.getElementById('submit-btn');

for (const name of ['research_level', 'competition_level', 'publication_level', 'project_level']) {
  const input = form.elements[name];
  const output = document.getElementById(`${name}_out`);
  input.addEventListener('input', () => { output.value = input.value; });
}

function splitList(value) {
  return value.split(/[,，]/).map(x => x.trim()).filter(Boolean);
}

function selectedValues(select) {
  return Array.from(select.selectedOptions).map(option => option.value);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function card(item) {
  const reasons = item.reasons.map(x => `<li>${escapeHtml(x)}</li>`).join('');
  const risks = item.risks.map(x => `<li>${escapeHtml(x)}</li>`).join('');
  return `
    <article class="card ${item.bucket}">
      <div class="card-top">
        <span class="bucket">${item.bucket}</span>
        <span class="score">匹配 ${item.match_score}</span>
      </div>
      <h3>${escapeHtml(item.school)}</h3>
      <p class="program">${escapeHtml(item.college)} · ${escapeHtml(item.program_name)}</p>
      <div class="metrics">
        <span>地区 ${escapeHtml(item.region)}</span>
        <span>置信度 ${item.confidence}%</span>
        <span>证据 ${item.evidence_level}</span>
      </div>
      <div class="details">
        <div><strong>匹配理由</strong><ul>${reasons || '<li>暂无</li>'}</ul></div>
        <div><strong>主要风险</strong><ul>${risks || '<li>暂无明显风险</li>'}</ul></div>
      </div>
    </article>`;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  submitBtn.disabled = true;
  submitBtn.textContent = '计算中…';
  results.className = 'results';
  results.innerHTML = '<div class="loading">正在生成可解释匹配结果…</div>';

  const payload = {
    school_name: form.elements.school_name.value.trim(),
    school_tier: form.elements.school_tier.value,
    major: form.elements.major.value.trim(),
    rank_percent: Number(form.elements.rank_percent.value),
    gpa: Number(form.elements.gpa.value),
    gpa_scale: Number(form.elements.gpa_scale.value),
    cet4: form.elements.cet4.value ? Number(form.elements.cet4.value) : null,
    cet6: form.elements.cet6.value ? Number(form.elements.cet6.value) : null,
    research_level: Number(form.elements.research_level.value),
    competition_level: Number(form.elements.competition_level.value),
    publication_level: Number(form.elements.publication_level.value),
    project_level: Number(form.elements.project_level.value),
    directions: splitList(form.elements.directions.value),
    preferred_regions: splitList(form.elements.preferred_regions.value),
    degree_types: selectedValues(form.elements.degree_types),
    risk_preference: form.elements.risk_preference.value,
  };

  try {
    const response = await fetch('/api/recommend?limit=18', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '请求失败');

    notice.textContent = data.disclaimer;
    summary.textContent = `申请者强度 ${data.profile_summary.applicant_strength} · 专业排名前 ${data.profile_summary.rank_percent}%`;
    results.innerHTML = data.recommendations.map(card).join('');
  } catch (error) {
    results.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = '生成匹配建议';
  }
});
