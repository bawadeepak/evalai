import { describe, expect, it } from 'vitest'
import { credentialRefError } from './ProvidersPage'
import { buildRunRequest, controlFor, type SetupForm } from './RunSetupPage'
import { buildDocument, suggestGraders, type Draft } from './ScenarioWizardPage'

const form: SetupForm = {
  name: '',
  scenarioId: 's',
  datasetId: 'd',
  baselineId: 'b',
  candidateIds: ['c1', 'c2'],
  graderIds: null,
  repeats: 5,
  repeatMode: 'full_episode',
  maxConcurrency: '',
  scheduleSeed: 42,
  maxTargetCalls: '',
  maxJudgeCalls: '',
  maxCost: '',
  timeoutSeconds: 120,
}

describe('run setup', () => {
  it('builds candidates with the baseline first and optional limits as null', () => {
    const body = buildRunRequest(form, 'p')
    expect(body.candidates).toEqual([
      { key: 'baseline', target_config_id: 'b' },
      { key: 'candidate', target_config_id: 'c1' },
      { key: 'candidate-2', target_config_id: 'c2' },
    ])
    expect(body.limits.max_target_calls).toBeNull()
    expect(body.execution.repeats).toBe(5)
  })

  it('links server error fields to the controls that fix them', () => {
    expect(controlFor('candidates[0].parameters.seed', true)).toBe('run-baseline')
    expect(controlFor('candidates[1].target_config_id', true)).toBe('run-candidate-0')
    expect(controlFor('candidates[0].parameters.seed', false)).toBe('run-candidate-0')
    expect(controlFor('candidates.2.parameters', true)).toBe('run-candidate-1')
    expect(controlFor('execution.repeats', true)).toBe('run-repeats')
    expect(controlFor('dataset_id', true)).toBe('run-dataset')
    expect(controlFor('something_else', true)).toBeNull()
  })
})

describe('provider credentials', () => {
  it('accepts environment variable names and rejects secret-looking values', () => {
    expect(credentialRefError('OPENAI_API_KEY')).toBeNull()
    expect(credentialRefError('')).toBeNull()
    expect(credentialRefError('sk-live-abcdef1234567890')).toMatch(/secret/)
    expect(credentialRefError('my key')).toMatch(/environment variable/)
  })
})

describe('scenario wizard', () => {
  it('preselects graders from the evidence answers, allowing several at once', () => {
    const graders = suggestGraders('exact_classification', { correct: true, reference: false, baseline: true, feedback: false })
    expect(graders.map((g) => g.name)).toEqual(['correctness', 'preference'])
    expect(graders[0]!.checks).toEqual(['label_match'])
    const rubric = suggestGraders('reference_answer', { correct: false, reference: false, baseline: false, feedback: true })
    expect(rubric.map((g) => g.kind)).toContain('model')
  })

  it('builds a document and reports invalid JSON fields', () => {
    const draft = {
      name: 'x',
      pack: 'exact_classification',
      contract: 'Route it.',
      description: '',
      evidence: { correct: true, reference: null, baseline: null, feedback: null },
      allowedLabels: 'a, b',
      eventDefinition: '',
      inputSchema: '',
      outputSchema: '',
      tools: '',
      corpus: '',
      graders: [{ name: 'label', kind: 'deterministic', checks: ['label_match'] }],
      judges: {},
      sliceKeys: 'queue',
      criticalInvariants: [],
      datasetName: '',
      cases: '',
      parentId: null,
      reason: '',
    } satisfies Draft
    const built = buildDocument(draft)
    expect(built.document).toMatchObject({ allowed_labels: ['a', 'b'], slice_keys: ['queue'], schema_version: 1 })
    expect(built.document).not.toHaveProperty('dataset')
    expect(buildDocument({ ...draft, inputSchema: '{bad' }).error).toMatch(/Input schema/)
  })
})
