// ════════════════════════════════════════
// 前端模块 Node.js 单元测试
// 测试 data-normalizer.js 和 analysis-renderer.js 的纯逻辑函数
//
// 运行：node tests/test_frontend_modules.mjs
// ════════════════════════════════════════

import {
  pickField,
  tryParseDict,
  extractPyField,
  normalizeHighlight,
  normalizeUseCase,
  renderInsightItem,
} from '../dashboard_static/js/utils/data-normalizer.js';

import {
  renderProjectCard,
  renderComparisonSection,
  renderAnalysisContainer,
} from '../dashboard_static/js/utils/analysis-renderer.js';

import { escapeHtml, pickTagColor } from '../dashboard_static/js/utils.js';

let passed = 0;
let failed = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    passed++;
  } catch (e) {
    failed++;
    failures.push({ name, error: e.message });
  }
}

function assert(condition, msg) {
  if (!condition) throw new Error(msg || 'Assertion failed');
}

function assertEqual(actual, expected, msg) {
  if (actual !== expected) {
    throw new Error(`${msg || ''}: expected "${expected}", got "${actual}"`);
  }
}

function assertIncludes(str, substr, msg) {
  if (!str || !str.includes(substr)) {
    throw new Error(`${msg || ''}: expected to include "${substr}" in "${str?.substring(0, 100)}..."`);
  }
}

function assertNotIncludes(str, substr, msg) {
  if (str && str.includes(substr)) {
    throw new Error(`${msg || ''}: should not include "${substr}"`);
  }
}

// ════════════════════════════════════════
// 1. data-normalizer.js: pickField
// ════════════════════════════════════════

test('pickField: 返回第一个非空值', () => {
  assertEqual(pickField({ a: '', b: 'hello', c: 'world' }, ['a', 'b', 'c']), 'hello');
});

test('pickField: 无匹配返回空字符串', () => {
  assertEqual(pickField({ a: 'x' }, ['b', 'c']), '');
});

test('pickField: null/undefined 输入返回空字符串', () => {
  assertEqual(pickField(null, ['a']), '');
  assertEqual(pickField(undefined, ['a']), '');
  assertEqual(pickField('not-object', ['a']), '');
});

test('pickField: null 值被跳过', () => {
  assertEqual(pickField({ a: null, b: undefined, c: 'val' }, ['a', 'b', 'c']), 'val');
});

test('pickField: 数字值被转为字符串', () => {
  assertEqual(pickField({ count: 42 }, ['count']), '42');
});

// ════════════════════════════════════════
// 2. data-normalizer.js: tryParseDict
// ════════════════════════════════════════

test('tryParseDict: 合法 JSON 字符串', () => {
  const result = tryParseDict('{"key": "value"}');
  assert(result !== null, 'should not be null');
  assertEqual(result.key, 'value');
});

test('tryParseDict: Python repr dict 字符串', () => {
  const result = tryParseDict("{'key': 'value'}");
  assert(result !== null, 'should not be null');
  assertEqual(result.key, 'value');
});

test('tryParseDict: Python True/False/None', () => {
  const result = tryParseDict("{'flag': True, 'val': None}");
  assert(result !== null, 'should not be null');
  assertEqual(result.flag, true);
  assertEqual(result.val, null);
});

test('tryParseDict: 非对象返回 null', () => {
  assertEqual(tryParseDict('hello'), null);
  assertEqual(tryParseDict('[1,2,3]'), null);
  assertEqual(tryParseDict(''), null);
});

test('tryParseDict: 非 dict 格式返回 null', () => {
  assertEqual(tryParseDict('[object Object]'), null);
  assertEqual(tryParseDict('not a dict'), null);
});

test('tryParseDict: 转义单引号', () => {
  const result = tryParseDict("{'key': 'it\\'s value'}");
  assert(result !== null, 'should not be null');
  assertEqual(result.key, "it's value");
});

// ════════════════════════════════════════
// 3. data-normalizer.js: extractPyField
// ════════════════════════════════════════

test('extractPyField: 提取字段值', () => {
  const result = extractPyField("{'point': 'Fast API', 'value': 'good'}", 'point');
  assertEqual(result, 'Fast API');
});

test('extractPyField: 无匹配返回空', () => {
  const result = extractPyField("{'a': 'b'}", 'nonexistent');
  assertEqual(result, '');
});

test('extractPyField: 双引号键值', () => {
  const result = extractPyField('{"point": "Double Quotes"}', 'point');
  assertEqual(result, 'Double Quotes');
});

// ════════════════════════════════════════
// 4. data-normalizer.js: normalizeHighlight
// ════════════════════════════════════════

test('normalizeHighlight: JS 对象 {point, value}', () => {
  const result = normalizeHighlight({ point: 'Fast', value: 'Good' });
  assert(result !== null, 'should not be null');
  assertEqual(result.title, 'Fast');
  assertEqual(result.desc, 'Good');
});

test('normalizeHighlight: 纯字符串', () => {
  const result = normalizeHighlight('simple highlight');
  assert(result !== null, 'should not be null');
  assertEqual(result.title, '');
  assertEqual(result.desc, 'simple highlight');
});

test('normalizeHighlight: Python repr dict 字符串', () => {
  const result = normalizeHighlight("{'point': 'Speed', 'value': 'very fast'}");
  assert(result !== null, 'should not be null');
  assertEqual(result.title, 'Speed');
  assertEqual(result.desc, 'very fast');
});

test('normalizeHighlight: null 返回 null', () => {
  assertEqual(normalizeHighlight(null), null);
  assertEqual(normalizeHighlight(undefined), null);
});

test('normalizeHighlight: 空对象返回 null', () => {
  assertEqual(normalizeHighlight({}), null);
});

test('normalizeHighlight: {title, desc} 兼容', () => {
  const result = normalizeHighlight({ title: 'T', desc: 'D' });
  assert(result !== null);
  assertEqual(result.title, 'T');
  assertEqual(result.desc, 'D');
});

// ════════════════════════════════════════
// 5. data-normalizer.js: normalizeUseCase
// ════════════════════════════════════════

test('normalizeUseCase: JS 对象 {who, scenario, solve}', () => {
  const result = normalizeUseCase({ who: 'Developers', scenario: 'CI/CD', solve: 'Automation' });
  assert(result !== null, 'should not be null');
  assertEqual(result.title, 'Developers');
  assertIncludes(result.desc, 'CI/CD');
  assertIncludes(result.desc, 'Automation');
});

test('normalizeUseCase: 纯字符串', () => {
  const result = normalizeUseCase('just a use case');
  assert(result !== null, 'should not be null');
  assertEqual(result.title, '');
  assertEqual(result.desc, 'just a use case');
});

test('normalizeUseCase: null 返回 null', () => {
  assertEqual(normalizeUseCase(null), null);
});

test('normalizeUseCase: 只有 scenario', () => {
  const result = normalizeUseCase({ scenario: 'Testing' });
  assert(result !== null);
  assertIncludes(result.desc, 'Testing');
});

// ════════════════════════════════════════
// 6. data-normalizer.js: renderInsightItem
// ════════════════════════════════════════

test('renderInsightItem: title + desc', () => {
  const html = renderInsightItem({ title: 'Speed', desc: 'Fast' }, (s) => s);
  assertIncludes(html, '<strong>Speed</strong>');
  assertIncludes(html, 'Fast');
});

test('renderInsightItem: 只有 title', () => {
  const html = renderInsightItem({ title: 'Only', desc: '' }, (s) => s);
  assertIncludes(html, '<strong>Only</strong>');
});

test('renderInsightItem: 只有 desc', () => {
  const html = renderInsightItem({ title: '', desc: 'Description' }, (s) => s);
  assertIncludes(html, 'Description');
  assert(!html.includes('<strong>'), 'should not contain strong tag');
});

test('renderInsightItem: null 返回空字符串', () => {
  assertEqual(renderInsightItem(null), '');
});

test('renderInsightItem: 转义函数应用', () => {
  const html = renderInsightItem({ title: '<b>', desc: '<script>' }, (s) => `&${s};`);
  assertIncludes(html, '&<b>;');
});

// ════════════════════════════════════════
// 7. utils.js: escapeHtml
// ════════════════════════════════════════

test('escapeHtml: 基本转义', () => {
  assertEqual(escapeHtml('<div>'), '&lt;div&gt;');
  assertEqual(escapeHtml('"quote"'), '&quot;quote&quot;');
  assertEqual(escapeHtml("&"), '&amp;');
  assertEqual(escapeHtml("'"), '&#39;');
});

test('escapeHtml: null/undefined 返回空', () => {
  assertEqual(escapeHtml(null), '');
  assertEqual(escapeHtml(undefined), '');
});

test('escapeHtml: 无特殊字符不修改', () => {
  assertEqual(escapeHtml('hello world'), 'hello world');
});

test('escapeHtml: 数字被转为字符串', () => {
  assertEqual(escapeHtml(42), '42');
});

// ════════════════════════════════════════
// 8. utils.js: pickTagColor
// ════════════════════════════════════════

test('pickTagColor: 返回颜色值', () => {
  const color = pickTagColor('Python');
  assert(typeof color === 'string');
  assert(color.startsWith('#'), 'should be hex color');
});

test('pickTagColor: 相同标签返回相同颜色', () => {
  const c1 = pickTagColor('React');
  const c2 = pickTagColor('React');
  assertEqual(c1, c2);
});

test('pickTagColor: 空字符串不崩溃', () => {
  const color = pickTagColor('');
  assert(typeof color === 'string');
});

// ════════════════════════════════════════
// 9. analysis-renderer.js: renderProjectCard
// ════════════════════════════════════════

test('renderProjectCard: 基本字段渲染', () => {
  const proj = {
    repo_name: 'test/repo',
    summary: 'A test project',
    tech_stack: ['Python', 'Rust'],
  };
  const html = renderProjectCard(proj, 0, 1, 1, { showQA: false });
  assertIncludes(html, 'test/repo');
  assertIncludes(html, 'A test project');
  assertIncludes(html, 'Python');
  assertIncludes(html, 'Rust');
  assertIncludes(html, 'proj-card');
});

test('renderProjectCard: 空数据不崩溃', () => {
  const html = renderProjectCard({}, 0, 1, 1, { showQA: false });
  assertIncludes(html, 'proj-card');
  assertIncludes(html, '未命名项目');
});

test('renderProjectCard: null 数据不崩溃', () => {
  const html = renderProjectCard(null, 0, 1, 1, { showQA: false });
  assertIncludes(html, 'proj-card');
});

test('renderProjectCard: tech_stack 非数组不崩溃', () => {
  const html = renderProjectCard({ tech_stack: 'not-array' }, 0, 1, 1, { showQA: false });
  assertIncludes(html, 'proj-card');
});

test('renderProjectCard: showQA=true 渲染 QA 面板', () => {
  const html = renderProjectCard({ repo_name: 'test' }, 0, 1, 1, { showQA: true });
  assertIncludes(html, 'qa-panel');
  assertIncludes(html, 'qa-input');
});

test('renderProjectCard: showQA=false 不渲染 QA', () => {
  const html = renderProjectCard({ repo_name: 'test' }, 0, 1, 1, { showQA: false });
  assertNotIncludes(html, 'qa-panel');
});

test('renderProjectCard: 健康度面板', () => {
  const proj = {
    repo_name: 'test',
    health_data: {
      health_grade: 'A',
      health_score: 85,
      commit_count_30d: 42,
      contributor_count: 8,
    },
  };
  const html = renderProjectCard(proj, 0, 1, 1, { showQA: false });
  assertIncludes(html, 'health-panel');
  assertIncludes(html, '85');
  assertIncludes(html, '42');
});

test('renderProjectCard: 质量评分徽章', () => {
  const html = renderProjectCard({ repo_name: 'test', review_score: 8.5 }, 0, 1, 1, { showQA: false });
  assertIncludes(html, 'review-badge');
  assertIncludes(html, '8.5');
});

test('renderProjectCard: 质量评分为 0 不渲染徽章', () => {
  const html = renderProjectCard({ repo_name: 'test', review_score: 0 }, 0, 1, 1, { showQA: false });
  assertNotIncludes(html, 'reviewbadge');
});

test('renderProjectCard: 依赖清单渲染（字符串数组）', () => {
  const html = renderProjectCard({
    repo_name: 'test',
    dependencies: ['requests', 'flask'],
  }, 0, 1, 1, { showQA: false });
  assertIncludes(html, 'dep-tag');
  assertIncludes(html, 'requests');
  assertIncludes(html, 'flask');
});

test('renderProjectCard: 依赖清单渲染（对象数组）', () => {
  const html = renderProjectCard({
    repo_name: 'test',
    dependencies: [{ name: 'pytest', version: '>=7.0' }],
  }, 0, 1, 1, { showQA: false });
  assertIncludes(html, 'dep-tag');
  assertIncludes(html, 'pytest');
  // escapeHtml 将 > 转义为 &gt;
  assertIncludes(html, '&gt;=7.0');
});

test('renderProjectCard: 代码指标面板', () => {
  const html = renderProjectCard({
    repo_name: 'test',
    code_metrics: {
      architecture_pattern: 'MVC',
      architecture_confidence: 0.85,
      total_loc: 5000,
      file_count: 42,
      complexity_score: 6,
      quality_score: 75,
    },
  }, 0, 1, 1, { showQA: false });
  assertIncludes(html, 'code-metrics-panel');
  assertIncludes(html, 'MVC');
  assertIncludes(html, '5000');
});

test('renderProjectCard: HTML 注入防护', () => {
  const html = renderProjectCard({
    repo_name: '<script>alert(1)</script>',
    summary: '<img onerror=alert(1)>',
  }, 0, 1, 1, { showQA: false });
  assertNotIncludes(html, '<script>alert(1)</script>');
  assertNotIncludes(html, '<img onerror');
});

test('renderProjectCard: 分隔符渲染（非最后一个项目）', () => {
  const html = renderProjectCard({ repo_name: 'test' }, 0, 3, 1, { showQA: false });
  assertIncludes(html, 'proj-divider');
});

test('renderProjectCard: 最后一个项目无分隔符', () => {
  const html = renderProjectCard({ repo_name: 'test' }, 2, 3, 1, { showQA: false });
  assertNotIncludes(html, 'proj-divider');
});

// ════════════════════════════════════════
// 10. analysis-renderer.js: renderComparisonSection
// ════════════════════════════════════════

test('renderComparisonSection: 完整数据', () => {
  const cmp = {
    tech_overlap: ['Python', 'Docker'],
    positioning_diff: 'Different focus areas',
    activity_ranking: [
      { name: 'repo-a', health_score: 80 },
      { name: 'repo-b', health_score: 60 },
    ],
    verdict: 'Both are good projects',
  };
  const html = renderComparisonSection(cmp);
  assertIncludes(html, 'comparison-section');
  assertIncludes(html, 'Python');
  assertIncludes(html, 'Docker');
  assertIncludes(html, 'Different focus');
  assertIncludes(html, 'repo-a');
  assertIncludes(html, 'Both are good');
});

test('renderComparisonSection: null 返回空', () => {
  assertEqual(renderComparisonSection(null), '');
  assertEqual(renderComparisonSection(undefined), '');
});

test('renderComparisonSection: 空对象返回空', () => {
  assertEqual(renderComparisonSection({}), '');
});

test('renderComparisonSection: 只有 tech_overlap', () => {
  const html = renderComparisonSection({ tech_overlap: ['Go'] });
  assertIncludes(html, 'comparison-section');
  assertIncludes(html, 'Go');
});

// ════════════════════════════════════════
// 11. analysis-renderer.js: renderAnalysisContainer
// ════════════════════════════════════════

test('renderAnalysisContainer: 正常数据', () => {
  const data = {
    analyses: [
      { repo_name: 'test/repo1', summary: 'Project 1' },
      { repo_name: 'test/repo2', summary: 'Project 2' },
    ],
  };
  const html = renderAnalysisContainer(data, 1);
  assertIncludes(html, 'analysis-header');
  assertIncludes(html, 'test/repo1');
  assertIncludes(html, 'test/repo2');
});

test('renderAnalysisContainer: 空分析数据', () => {
  const html = renderAnalysisContainer({ analyses: [] }, 1);
  assertIncludes(html, '暂无分析数据');
});

test('renderAnalysisContainer: 无 analyses 字段', () => {
  const html = renderAnalysisContainer({}, 1);
  assertIncludes(html, '暂无分析数据');
});

test('renderAnalysisContainer: null 数据', () => {
  const html = renderAnalysisContainer(null, 1);
  assertIncludes(html, '暂无分析数据');
});

test('renderAnalysisContainer: 不含 comparison（comparison 需单独渲染）', () => {
  const data = {
    analyses: [{ repo_name: 'test' }],
    comparison: {
      tech_overlap: ['Python'],
      verdict: 'Great project',
    },
  };
  const html = renderAnalysisContainer(data, 1);
  // container 只渲染项目卡片，comparison 需通过 renderComparisonSection 单独渲染
  assertIncludes(html, 'test');
  assertNotIncludes(html, 'Great project');

  // comparison 需单独渲染
  const cmpHtml = renderComparisonSection(data.comparison);
  assertIncludes(cmpHtml, 'Python');
  assertIncludes(cmpHtml, 'Great project');
});

// ════════════════════════════════════════
// 12. 集成测试：完整渲染流程
// ════════════════════════════════════════

test('集成: 完整项目渲染含所有字段', () => {
  const data = {
    analyses: [{
      repo_name: 'facebook/react',
      summary: 'A JavaScript library for building UIs',
      tech_stack: ['JavaScript', 'TypeScript'],
      architecture: 'Component-based with virtual DOM',
      key_modules: [
        { name: 'react', description: 'Core library' },
        { name: 'react-dom', description: 'DOM rendering' },
      ],
      quick_start: 'npm install react react-dom',
      highlights: [
        { point: 'Virtual DOM', value: 'Efficient updates' },
        'Simple and declarative',
      ],
      use_cases: [
        { who: 'Web Developers', scenario: 'Building SPAs', solve: 'Faster development' },
      ],
      code_metrics: {
        architecture_pattern: 'Component',
        architecture_confidence: 0.9,
        total_loc: 10000,
        file_count: 50,
      },
      review_score: 9.0,
      health_data: {
        health_grade: 'A',
        health_score: 90,
        commit_count_30d: 100,
        contributor_count: 500,
      },
      dependencies: [
        { name: 'lodash', version: '>=4.0' },
        'scheduler',
      ],
    }],
    comparison: {
      tech_overlap: ['JavaScript'],
      verdict: 'React is the most popular',
    },
  };

  const html = renderAnalysisContainer(data, 1);
  const card = renderProjectCard(data.analyses[0], 0, 1, 1, { showQA: true });
  const cmp = renderComparisonSection(data.comparison);

  assertIncludes(html, 'facebook/react');
  assertIncludes(card, 'Component-based');
  assertIncludes(card, 'react-dom');
  assertIncludes(card, 'npm install');
  assertIncludes(card, 'Virtual DOM');
  assertIncludes(card, 'Web Developers');
  assertIncludes(card, '9.0');
  assertIncludes(card, 'health-panel');
  assertIncludes(card, 'lodash');
  assertIncludes(card, 'qa-panel');
  assertIncludes(cmp, 'JavaScript');
  assertIncludes(cmp, 'most popular');
});

// ════════════════════════════════════════
// 输出结果
// ════════════════════════════════════════

console.log('\n═══════════════════════════════════════');
console.log('  前端模块单元测试结果');
console.log('═══════════════════════════════════════');
console.log(`  总计: ${passed + failed}`);
console.log(`  通过: ${passed}`);
console.log(`  失败: ${failed}`);

if (failures.length > 0) {
  console.log('\n--- 失败详情 ---');
  failures.forEach(f => {
    console.log(`  ✗ ${f.name}`);
    console.log(`    ${f.error}`);
  });
}

console.log('\n' + (failed === 0 ? '✓ 全部通过' : `✗ ${failed} 个测试失败`));
process.exit(failed > 0 ? 1 : 0);
