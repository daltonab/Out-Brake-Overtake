import pooledOutBrakingModel from '../../../public/models/pooled-out-braking.json'

export type ScenarioValues = Record<string, number | string | boolean | null>

type BrowserModel = typeof pooledOutBrakingModel

const model: BrowserModel = pooledOutBrakingModel

function categorySuffix(value: string | boolean | null) {
  if (value === null) return 'None'
  if (typeof value === 'boolean') return value ? 'True' : 'False'
  return value
}

function calibratedProbability(rawProbability: number) {
  if (!model.calibration) return rawProbability
  if (model.calibration.method !== 'platt_scaling') throw new Error('Unsupported model calibration')
  const bounded = Math.min(Math.max(rawProbability, 0.000001), 0.999999)
  const rawLogit = Math.log(bounded / (1 - bounded))
  const calibratedLogit = model.calibration.coefficient * rawLogit + model.calibration.intercept
  return 1 / (1 + Math.exp(-calibratedLogit))
}

export function predictOvertake(values: ScenarioValues) {
  const encoded = new Map<string, number>()

  model.numeric.features.forEach((feature, index) => {
    const raw = values[feature]
    const value = typeof raw === 'number' && Number.isFinite(raw) ? raw : model.numeric.impute_medians[index]
    encoded.set(`numeric__${feature}`, (value - model.numeric.means[index]) / model.numeric.scales[index])
  })

  model.categorical.features.forEach((feature, index) => {
    const raw = values[feature]
    const value = typeof raw === 'string' || typeof raw === 'boolean' || raw === null ? raw : model.categorical.impute_values[index]
    encoded.set(`categorical__${feature}_${categorySuffix(value)}`, 1)
  })

  const score = model.encoded_feature_order.reduce((total, feature, index) => total + (encoded.get(feature) ?? 0) * model.coefficients[index], model.intercept)
  const rawProbability = 1 / (1 + Math.exp(-score))
  const probability = calibratedProbability(rawProbability)
  return { probability, isLikely: probability >= model.decision_threshold }
}

export { model as pooledOutBrakingModel }
