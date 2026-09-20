import { cloneElement, isValidElement } from 'react'
import { Autocomplete, Box, Chip, TextField, Tooltip, Typography } from '@mui/material'

const defaultOptionLabel = (option) => String(option?.label ?? option?.name ?? option ?? '').trim()
const defaultOptionEquality = (option, value) => {
  const optionId = option?.id ?? option?.key
  const valueId = value?.id ?? value?.key
  return optionId != null || valueId != null ? optionId === valueId : defaultOptionLabel(option) === defaultOptionLabel(value)
}

export const normalizeCreatableValues = (values) => {
  const seen = new Set()
  return (Array.isArray(values) ? values : []).reduce((result, item) => {
    const value = defaultOptionLabel(item).trim()
    const key = value.toLocaleLowerCase()
    if (value && !seen.has(key)) {
      seen.add(key)
      result.push(value)
    }
    return result
  }, [])
}

const boxedMultiselectSx = {
  width: '100%',
  minWidth: 0,
  '& .MuiInputBase-root, & .MuiAutocomplete-inputRoot': {
    height: 40,
    minHeight: 40,
    maxHeight: 40,
    alignItems: 'center',
    flexWrap: 'nowrap',
    overflow: 'hidden',
  },
  '& .MuiAutocomplete-inputRoot': {
    py: '0 !important',
    paddingRight: '4px !important',
  },
  '&:not(.MuiAutocomplete-hasClearIcon) .MuiAutocomplete-inputRoot': {
    paddingRight: '28px !important',
  },
  '& .MuiAutocomplete-input': {
    minWidth: '0 !important',
  },
  '&.MuiAutocomplete-hasClearIcon .MuiAutocomplete-input': {
    flex: '0 1 2px !important',
    width: '2px !important',
    minWidth: '2px !important',
  },
  '& .MuiAutocomplete-endAdornment': {
    right: '4px !important',
    display: 'flex',
    zIndex: 20,
  },
  '& .MuiAutocomplete-clearIndicator, & .MuiAutocomplete-popupIndicator': {
    width: 24,
    height: 24,
    p: '2px !important',
    bgcolor: 'background.paper',
    '&:hover': { bgcolor: 'action.hover' },
  },
  '& .MuiAutocomplete-clearIndicator': {
    display: 'none',
  },
  '&:hover .MuiAutocomplete-clearIndicator, &.Mui-focused .MuiAutocomplete-clearIndicator': {
    display: 'inline-flex',
    visibility: 'visible',
  },
  '& .MuiAutocomplete-tag': {
    my: 0,
    maxHeight: 24,
  },
}

const BoxedSelectionTags = ({ selected, getTagProps, getOptionLabel }) => {
  if (!selected.length) return null

  return (
    <Box
      sx={{
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        flex: '1 1 0',
        maxWidth: '100%',
        minWidth: 0,
        overflow: 'hidden',
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          flex: '0 0 auto',
          minWidth: 'max-content',
          gap: 0.5,
          overflow: 'visible',
        }}
      >
        {selected.map((option, index) => {
          const tagProps = getTagProps({ index })
          const { key, ...editableTagProps } = tagProps
          return (
            <Chip
              {...editableTagProps}
              key={key || `${getOptionLabel(option)}-${option?.id ?? option?.key ?? index}`}
              size="small"
              label={getOptionLabel(option)}
              sx={{ flex: '0 0 auto', maxWidth: 180 }}
            />
          )
        })}
      </Box>
    </Box>
  )
}

const BoxedSelectionCounter = ({ selected, getOptionLabel, tooltipLabel, onRemove }) => {
  if (!selected.length) return null
  const tooltipText = String(tooltipLabel || 'Elementos')

  return (
    <Tooltip
      arrow
      placement="top"
      enterDelay={150}
      disableInteractive={false}
      slotProps={{
        popper: { sx: { zIndex: (theme) => theme.zIndex.tooltip + 20 } },
        tooltip: { sx: { maxWidth: 420, p: 1 } },
      }}
      title={(
        <Box>
          <Typography variant="caption" fontWeight={800} sx={{ display: 'block', mb: 0.6 }}>
            Selection of {tooltipText} ({selected.length})
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, maxWidth: 390, maxHeight: 220, overflowY: 'auto' }}>
            {selected.map((option, index) => (
              <Chip
                key={`${getOptionLabel(option)}-${option?.id ?? option?.key ?? index}`}
                size="small"
                label={getOptionLabel(option)}
                variant="outlined"
                onDelete={(event) => onRemove(index, event)}
                onMouseDown={(event) => event.stopPropagation()}
                onClick={(event) => event.stopPropagation()}
              />
            ))}
          </Box>
        </Box>
      )}
    >
      <Box
        component="span"
        role="button"
        tabIndex={0}
        aria-label={`View full ${tooltipText.toLowerCase()} selection: ${selected.length}`}
        onMouseDown={(event) => { event.preventDefault(); event.stopPropagation() }}
        onClick={(event) => event.stopPropagation()}
        sx={{
          flex: '0 0 auto',
          zIndex: 1,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: 24,
          minWidth: 36,
          px: 0.8,
          border: 1,
          borderColor: 'divider',
          borderRadius: 999,
          bgcolor: 'background.paper',
          backgroundImage: 'none',
          color: 'text.primary',
          fontSize: 12,
          fontWeight: 800,
          lineHeight: 1,
          cursor: 'help',
          pointerEvents: 'auto',
          boxShadow: (theme) => `-6px 0 7px ${theme.palette.background.paper}`,
        }}
      >
        {selected.length}
      </Box>
    </Tooltip>
  )
}

export const BoxedMultiselect = ({
  value = [],
  getOptionLabel = defaultOptionLabel,
  tooltipLabel = 'Elementos',
  renderTags,
  renderInput,
  getOptionSecondaryText,
  onChange,
  size = 'small',
  sx,
  ...props
}) => {
  const selected = Array.isArray(value) ? value : []
  const removeSelected = (index, event) => {
    event?.preventDefault?.()
    event?.stopPropagation?.()
    const removedOption = selected[index]
    const nextValue = selected.filter((_, selectedIndex) => selectedIndex !== index)
    onChange?.(event, nextValue, 'removeOption', { option: removedOption })
  }
  const renderInputWithCounter = typeof renderInput === 'function'
    ? (params) => {
        const endAdornment = params.InputProps?.endAdornment
        const counter = selected.length ? (
          <BoxedSelectionCounter
            selected={selected}
            getOptionLabel={getOptionLabel}
            tooltipLabel={tooltipLabel}
            onRemove={removeSelected}
          />
        ) : null
        const nextEndAdornment = counter && isValidElement(endAdornment)
          ? cloneElement(endAdornment, undefined, counter, endAdornment.props.children)
          : endAdornment
        return renderInput({
          ...params,
          InputProps: {
            ...params.InputProps,
            endAdornment: nextEndAdornment,
          },
        })
      }
    : renderInput

  return (
    <Autocomplete
      {...props}
      multiple
      size={size}
      value={selected}
      onChange={onChange}
      getOptionLabel={getOptionLabel}
      isOptionEqualToValue={props.isOptionEqualToValue || defaultOptionEquality}
      renderOption={props.renderOption || (getOptionSecondaryText ? ((optionProps, option) => {
        const { key, ...rest } = optionProps
        return <li key={key} {...rest}><Box sx={{ display: 'grid' }}><span>{getOptionLabel(option)}</span><Typography variant="caption" color="text.secondary">{getOptionSecondaryText(option)}</Typography></Box></li>
      }) : undefined)}
      renderInput={renderInputWithCounter}
      renderTags={renderTags || ((tags, getTagProps) => (
        <BoxedSelectionTags
          selected={tags}
          getTagProps={getTagProps}
          getOptionLabel={getOptionLabel}
        />
      ))}
      sx={[boxedMultiselectSx, ...(Array.isArray(sx) ? sx : [sx].filter(Boolean))]}
    />
  )
}

export const BoxedMultiselectFilter = ({
  label,
  placeholder = 'Buscar',
  required = false,
  InputLabelProps,
  textFieldProps,
  renderInput,
  tooltipLabel = label || 'Elementos',
  filterSelectedOptions = true,
  disableCloseOnSelect = true,
  openOnFocus = true,
  ...props
}) => (
  <BoxedMultiselect
    {...props}
    tooltipLabel={tooltipLabel}
    filterSelectedOptions={filterSelectedOptions}
    disableCloseOnSelect={disableCloseOnSelect}
    openOnFocus={openOnFocus}
    renderInput={renderInput || ((params) => (
      <TextField
        {...params}
        {...textFieldProps}
        label={label}
        required={required}
        placeholder={props.value?.length ? '' : placeholder}
        InputLabelProps={InputLabelProps}
      />
    ))}
  />
)

export const CreatableBoxedMultiselect = ({ value = [], onChange, options = [], ...props }) => (
  <BoxedMultiselectFilter
    {...props}
    freeSolo
    options={normalizeCreatableValues(options)}
    value={normalizeCreatableValues(value)}
    onChange={(event, nextValue, reason, details) => onChange?.(event, normalizeCreatableValues(nextValue), reason, details)}
    getOptionLabel={defaultOptionLabel}
  />
)

export default BoxedMultiselectFilter
