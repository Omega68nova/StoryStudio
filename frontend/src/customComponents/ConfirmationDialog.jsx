import * as React from 'react'
import { useCanAccess, useDataProvider, useNotify, useRecordContext } from 'react-admin'
import { useFormContext, useWatch } from 'react-hook-form'
import {
  Box,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Button,
  FormControlLabel,
  FormGroup,
  Typography,
  TextField,
} from '@mui/material'
import useCTERefChoices from '../hooks/useCTERefChoices.js'

const stateColor = (state) => {
  if (state === 'Aceptada') return 'success.main'
  if (state === 'Rechazada' || state === 'Denegada') return 'error.main'
  if (state === 'Pendiente') return 'warning.main'
  return 'grey.400'
}

const stateLabel = (state) => {
  if (state === 'Aceptada') return 'Aceptada'
  if (state === 'Rechazada' || state === 'Denegada') return 'Rechazada'
  if (state === 'Pendiente') return 'Pendiente'
  return 'Sin solicitud'
}

const Dot = ({ size = 10, state }) => (
  <Box
    sx={{
      width: size,
      height: size,
      borderRadius: '50%',
      bgcolor: stateColor(state),
      flex: '0 0 auto',
    }}
  />
)

const kill = (e) => {
  e?.preventDefault?.()
  e?.stopPropagation?.()
  e?.nativeEvent?.stopImmediatePropagation?.()
}

const sameSolicitudes = (a = [], b = []) => {
  if (a.length !== b.length) return false

  for (let i = 0; i < a.length; i += 1) {
    const left = a[i]
    const right = b[i]

    if (
      Number(left?.id) !== Number(right?.id) ||
      Number(left?.refn) !== Number(right?.refn) ||
      left?.state !== right?.state ||
      (left?.comentario ?? '') !== (right?.comentario ?? '')
    ) {
      return false
    }
  }

  return true
}

const getNextTtp = (values = [], tppChoices = []) => {
  if (!values.length) return null
  if (values.length > 3) return tppChoices?.at?.(-1)?.id ?? null
  return tppChoices?.[values.length - 1]?.id ?? null
}

const ConfirmCheck = ({ disabled = false, tppChoices = [], deferRequests = false }) => {
  const record = useRecordContext()
  const dataProvider = useDataProvider()
  const notify = useNotify()
  const { setValue } = useFormContext()

  const { refs: cteRefChoices, info } = useCTERefChoices()
  const tpps = useWatch({ name: 'tpps' }) || []
  const currentTpp = useWatch({ name: 'ttp' })
  const pendingSolicitudes = useWatch({ name: '_pendingSolicitudesCTE' }) || []

  // Crear solicitud
  const { canAccess: canCreateRequests, isLoading: isLoadingCreatePerm } = useCanAccess({
    action: 'create',
    resource: 'solicitudes_cte_empleados',
  })

  // Validar / cambiar estado
  const { canAccess: canValidateRequests, isLoading: isLoadingValidatePerm } = useCanAccess({
    action: 'list',
    resource: 'validarsolicitudes',
  })

  const [solicitudes, setSolicitudes] = React.useState([])
  const [loadingSolicitudes, setLoadingSolicitudes] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const syncMainCTE = React.useCallback(
    async ({ refn, state }) => {
      if (!record?.id || !refn) return

      const params = {
        idhpt: record.id,
        refn,
        state,
      }

      const res = await fetch(`https://api.${import.meta.env.VITE_BASE_URL}/partestrabajo-api/updatetpps`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          Authorization: `Bearer ${localStorage.getItem('jwt')}`,
        },
        body: JSON.stringify(params),
      })

      if (!res.ok) {
        throw new Error('No se pudo sincronizar el CTE principal')
      }

      return res.json().catch(() => null)
    },
    [record?.id]
  )
  const loadSolicitudes = React.useCallback(
    async ({ silent = false } = {}) => {
      if (!record?.id) return

      if (!silent && solicitudes.length === 0) {
        setLoadingSolicitudes(true)
      }

      try {
        const res = await dataProvider.getList('solicitudes_cte_empleados', {
          pagination: { page: 1, perPage: 500 },
          sort: { field: 'id', order: 'DESC' },
          filter: { idhpt: record.id },
        })

        const next = res?.data || []
        setSolicitudes((prev) => (sameSolicitudes(prev, next) ? prev : next))
      } catch (e) {
        notify('Error cargando solicitudes_cte_empleados', { type: 'warning' })
        console.error(e)
      } finally {
        setLoadingSolicitudes(false)
      }
    },
    [dataProvider, notify, record?.id, solicitudes.length]
  )

  React.useEffect(() => {
    if (!record?.id) return

    loadSolicitudes()

    const intervalMs = 5000
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        loadSolicitudes({ silent: true })
      }
    }, intervalMs)

    return () => window.clearInterval(id)
  }, [record?.id, loadSolicitudes])

  React.useEffect(() => {
    if (!record?.id) return

    const onVis = () => {
      if (document.visibilityState === 'visible') {
        loadSolicitudes({ silent: true })
      }
    }

    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [record?.id, loadSolicitudes])

  const solicitudesByRefn = React.useMemo(() => {
    const map = new Map()
    for (const s of solicitudes) {
      const key = Number(s?.refn)
      if (!map.has(key)) map.set(key, s)
    }
    return map
  }, [solicitudes])

  const getSolicitud = React.useCallback((refnId) => solicitudesByRefn.get(Number(refnId)) || null, [solicitudesByRefn])
  const getPendingSolicitud = React.useCallback(
    (refnId) => pendingSolicitudes.find((s) => Number(s?.refn) === Number(refnId)) || null,
    [pendingSolicitudes]
  )

  const hasSolicitudAccepted = React.useCallback((refnId) => getSolicitud(refnId)?.state === 'Aceptada', [getSolicitud])

  React.useEffect(() => {
    if (!cteRefChoices?.length) return

    const requires = cteRefChoices.filter((c) => c?.requiresConfirmation)
    if (!requires.length) return

    const requiredIds = requires.map((c) => Number(c.id))
    const acceptedIds = requiredIds.filter((id) => hasSolicitudAccepted(id))

    const normal = (tpps || []).filter((id) => !requiredIds.includes(Number(id)))
    const merged = Array.from(new Set([...normal, ...acceptedIds]))

    const sameTpps =
      merged.length === (tpps || []).length && merged.every((id) => (tpps || []).some((x) => Number(x) === Number(id)))

    if (!sameTpps) {
      setValue('tpps', merged, { shouldDirty: false, shouldTouch: false })
    }

    const nextTpp = getNextTtp(merged, tppChoices)
    if (currentTpp !== nextTpp) {
      setValue('ttp', nextTpp, { shouldDirty: false, shouldTouch: false })
    }
  }, [cteRefChoices, hasSolicitudAccepted, tpps, currentTpp, setValue, tppChoices])

  const updateTtp = React.useCallback(
    (values) => {
      setValue('ttp', getNextTtp(values, tppChoices), { shouldDirty: false })
    },
    [setValue, tppChoices]
  )

  const [open, setOpen] = React.useState(false)
  const [activeChoice, setActiveChoice] = React.useState(null)
  const [comment, setComment] = React.useState('')

  const activeSolicitud = React.useMemo(
    () => (activeChoice?.id ? getSolicitud(activeChoice.id) || getPendingSolicitud(activeChoice.id) : null),
    [activeChoice, getSolicitud, getPendingSolicitud]
  )

  const openDialogFor = React.useCallback(
    (choice) => {
      const existing = getSolicitud(choice?.id) || getPendingSolicitud(choice?.id)
      setActiveChoice(choice)
      setComment(existing?.comentario ?? '')
      setOpen(true)
    },
    [getSolicitud, getPendingSolicitud]
  )

  const closeDialog = React.useCallback(() => {
    setOpen(false)
    setActiveChoice(null)
    setComment('')
  }, [])

  const createSolicitud = React.useCallback(async () => {
    if (deferRequests) {
      if (!activeChoice?.id || saving) return

      const cleanComment = (comment || '').trim()
      if (!cleanComment) return

      const next = [
        ...pendingSolicitudes.filter((s) => Number(s?.refn) !== Number(activeChoice.id)),
        {
          refn: activeChoice.id,
          comentario: cleanComment,
          state: 'Pendiente',
        },
      ]

      setValue('_pendingSolicitudesCTE', next, { shouldDirty: true })
      closeDialog()
      return
    }

    if (!record?.id || !activeChoice?.id || saving) return

    const cleanComment = (comment || '').trim()
    if (!cleanComment) return
    if (!canCreateRequests) return

    try {
      setSaving(true)

      await dataProvider.create('solicitudes_cte_empleados', {
        data: {
          idhpt: record.id,
          refn: activeChoice.id,
          comentario: cleanComment,
          state: 'Pendiente',
        },
      })

      await syncMainCTE({
        refn: activeChoice.id,
        state: 'Pendiente',
      })

      notify('Solicitud creada.', { type: 'info' })
      await loadSolicitudes({ silent: true })
      closeDialog()
    } catch (e) {
      notify('No se pudo crear la solicitud.', { type: 'warning' })
      console.error(e)
    } finally {
      setSaving(false)
    }
  }, [
    record?.id,
    deferRequests,
    activeChoice,
    saving,
    comment,
    canCreateRequests,
    pendingSolicitudes,
    setValue,
    dataProvider,
    notify,
    loadSolicitudes,
    closeDialog,
    syncMainCTE,
  ])

  const setSolicitudState = React.useCallback(
    async (nextState) => {
      if (!activeSolicitud?.id || saving) return
      if (!canValidateRequests) return

      try {
        setSaving(true)

        await dataProvider.update('solicitudes_cte_empleados', {
          id: activeSolicitud.id,
          data: { state: nextState },
          previousData: activeSolicitud,
        })

        await syncMainCTE({
          refn: activeSolicitud.refn,
          state: nextState,
        })

        notify('Estado actualizado.', { type: 'info' })
        await loadSolicitudes({ silent: true })
        closeDialog()
      } catch (e) {
        notify('No se pudo actualizar el estado.', { type: 'warning' })
        console.error(e)
      } finally {
        setSaving(false)
      }
    },
    [activeSolicitud, saving, canValidateRequests, dataProvider, notify, loadSolicitudes, closeDialog, syncMainCTE]
  )

  const canCreateThisRequest = !disabled && (deferRequests || (!activeSolicitud && canCreateRequests))
  const canValidateThisRequest = !deferRequests && !disabled && !!activeSolicitud && canValidateRequests

  return (
    <>
      <FormGroup
        sx={(theme) => ({
          flexDirection: 'column',
          gap: 0.25,
          '& .MuiFormControlLabel-label': {
            fontSize: '0.75rem',
            color: theme.palette.text.secondary,
          },
        })}
      >
        {(cteRefChoices || []).map((choice) => {
          const isReq = !!choice?.requiresConfirmation
          const solicitud = getSolicitud(choice.id) || getPendingSolicitud(choice.id)
          const checked = isReq
            ? deferRequests
              ? !!solicitud
              : solicitud?.state === 'Aceptada'
            : (tpps || []).some((id) => Number(id) === Number(choice.id))

          const label = choice?.name ?? choice?.label ?? String(choice?.id)

          if (isReq) {
            return (
              <FormControlLabel
                key={choice.id}
                disableTypography
                sx={{
                  mr: 0,
                  cursor: 'pointer',
                  alignItems: 'center',
                  '& .MuiFormControlLabel-label': {
                    flex: 1,
                    minWidth: 0,
                  },
                  '&:hover': {
                    bgcolor: disabled ? 'transparent' : 'action.hover',
                    borderRadius: 1,
                  },
                }}
                onClick={(e) => {
                  kill(e)
                  if (disabled) return
                  if (deferRequests && solicitud) {
                    const next = pendingSolicitudes.filter((s) => Number(s?.refn) !== Number(choice.id))
                    setValue('_pendingSolicitudesCTE', next, { shouldDirty: true })
                    return
                  }
                  openDialogFor(choice)
                }}
                control={<Checkbox size="small" checked={!!checked} disableRipple onChange={() => {}} />}
                label={
                  <Box
                    sx={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 1,
                      cursor: 'pointer',
                      userSelect: 'none',
                      px: 1,
                      py: 0.5,
                      borderRadius: 1,
                      minWidth: 0,
                      '&:hover': {
                        bgcolor: disabled ? 'transparent' : 'action.hover',
                      },
                    }}
                    onClick={(e) => {
                      kill(e)
                      if (disabled) return
                      if (deferRequests && solicitud) {
                        const next = pendingSolicitudes.filter((s) => Number(s?.refn) !== Number(choice.id))
                        setValue('_pendingSolicitudesCTE', next, { shouldDirty: true })
                        return
                      }
                      openDialogFor(choice)
                    }}
                  >
                    <Dot state={solicitud?.state} />
                    <Typography
                      variant="body2"
                      sx={{
                        lineHeight: 1.2,
                        fontSize: '0.75rem',
                        color: 'text.secondary',
                      }}
                    >
                      {label}
                    </Typography>
                    <Typography
                      variant="caption"
                      sx={{
                        opacity: 0.8,
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {/* {stateLabel(solicitud?.state)} */}
                    </Typography>
                  </Box>
                }
              />
            )
          }

          return (
            <FormControlLabel
              key={choice.id}
              disabled={disabled}
              control={
                <Checkbox
                  size="small"
                  checked={!!checked}
                  onChange={(e) => {
                    const next = e.target.checked
                      ? Array.from(new Set([...(tpps || []), choice.id]))
                      : (tpps || []).filter((x) => Number(x) !== Number(choice.id))

                    setValue('tpps', next, { shouldDirty: true })
                    updateTtp(next)
                  }}
                />
              }
              label={label}
            />
          )
        })}
      </FormGroup>

      <Dialog open={open} onClose={closeDialog} maxWidth="sm" fullWidth onClick={kill}>
        <DialogTitle>{activeChoice ? `Solicitud de Ref. ${activeChoice.id}` : 'Solicitud'}</DialogTitle>

        <DialogContent>
          {activeChoice && (
            <>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                <Typography variant="body2">
                  {activeChoice?.name ?? activeChoice?.label ?? String(activeChoice?.id)}
                </Typography>
              </Box>

              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <Dot state={activeSolicitud?.state} />
                <Typography variant="body2" sx={{ opacity: 0.85 }}>
                  Estado actual: <b>{loadingSolicitudes ? 'Cargando...' : stateLabel(activeSolicitud?.state)}</b>
                </Typography>
              </Box>
            </>
          )}

          <TextField
            label="Comentario"
            fullWidth
            multiline
            minRows={3}
            value={comment}
            onChange={(e) => {
              if (!activeSolicitud || deferRequests) setComment(e.target.value)
            }}
            variant="outlined"
            InputProps={{
              readOnly: (!!activeSolicitud && !deferRequests) || !canCreateThisRequest,
            }}
            disabled={saving || (!!activeSolicitud && !deferRequests)}
          />
        </DialogContent>

        <DialogActions>
          <Button
            onClick={(e) => {
              kill(e)
              closeDialog()
            }}
          >
            Cerrar
          </Button>

          {(deferRequests || !isLoadingCreatePerm) && canCreateThisRequest && (
            <Button
              variant="contained"
              onClick={(e) => {
                kill(e)
                createSolicitud()
              }}
              disabled={saving || !(comment || '').trim()}
            >
              {deferRequests && activeSolicitud ? 'Actualizar solicitud' : 'Crear solicitud'}
            </Button>
          )}

          {!isLoadingValidatePerm && canValidateThisRequest && (
            <>
              {activeSolicitud?.state === 'Pendiente' ? (
                <>
                  <Button
                    variant="contained"
                    color="success"
                    onClick={(e) => {
                      kill(e)
                      setSolicitudState('Aceptada')
                    }}
                    disabled={saving}
                  >
                    Aceptar
                  </Button>
                  <Button
                    variant="contained"
                    onClick={(e) => {
                      kill(e)
                      setSolicitudState('Rechazada')
                    }}
                    disabled={saving}
                  >
                    Rechazar
                  </Button>
                </>
              ) : (
                <Button
                  variant="contained"
                  color="warning"
                  onClick={(e) => {
                    kill(e)
                    setSolicitudState('Pendiente')
                  }}
                  disabled={saving}
                >
                  Resetear
                </Button>
              )}
            </>
          )}
        </DialogActions>
      </Dialog>

      <Box key="legalText" sx={{ mt: 1 }}>
        {info?.split('\n').map((line, index) => (
          <Typography key={index} variant="body2" color="text.secondary" sx={{ fontSize: '0.75rem' }}>
            {line}
          </Typography>
        ))}
      </Box>
    </>
  )
}

export default ConfirmCheck
