import maxVerstappenModel from '../../../public/models/max-verstappen.json'

export type ScenarioValues = Record<string, number | string | boolean | null>

type BrowserModel = typeof maxVerstappenModel

const model: BrowserModel = maxVerstappenModel

function categorySuffix(value: string | boolean | null) {
  if (value === null) return 'None'
  if (typeof value === 'boolean') return value ? 'True' : 'False'
  return value
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
  const probability = 1 / (1 + Math.exp(-score))
  return { probability, isLikely: probability >= model.decision_threshold }
}

export { model as maxVerstappenModel }
