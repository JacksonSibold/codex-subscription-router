export function isSelectableDefault(settings) {
  const selected = settings.models.find(model => model.id === settings.runtime.default_model);
  return Boolean(selected?.visible && settings.providers[selected.provider]?.enabled);
}

export function findSelectableDefault(settings) {
  return settings.models.find(model => model.visible && settings.providers[model.provider]?.enabled) || null;
}
