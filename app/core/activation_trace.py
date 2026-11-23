"""Activation diagnostics: fixed stages and internal IDs, never bearer data."""
from logging_utils import get_logger


def trace_activation(stage, *, activation=None, outcome='success', exc=None, **identifiers):
    context = dict(activation or {})
    values = {'activation_id': context.get('id'), 'user_id': context.get('vodum_user_id'),
              'generation': context.get('generation'), **identifiers}
    ids = ' '.join(f'{key}={value}' for key,value in values.items()
                   if key in {'activation_id','user_id','generation','server_id'}
                   and type(value) is int)
    status = getattr(getattr(exc,'response',None),'status_code',None)
    reason = str(exc) if isinstance(exc,ValueError) and str(exc) in {
        'activation_invalid','activation_wrong_account','activation_identity_conflict',
        'activation_reauthenticate','activation_configuration_error','activation_email_changed',
        'activation_mode_disabled','activation_server_error','portal_unavailable',
    } else '-'
    logger = get_logger('activation')
    emit = logger.info if outcome == 'success' else logger.warning
    emit('Activation stage=%s outcome=%s %s error_type=%s reason=%s http_status=%s',
         stage,outcome,ids,type(exc).__name__ if exc is not None else '-',reason,
         status if type(status) is int else '-')
