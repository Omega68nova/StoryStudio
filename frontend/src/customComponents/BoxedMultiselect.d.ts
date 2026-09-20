import type { JSX, SyntheticEvent } from "react";
import type { AutocompleteProps } from "@mui/material";

export type BoxedMultiselectProps<T> = Omit<AutocompleteProps<T, true, false, false>, "multiple" | "renderInput" | "onChange"> & {
  tooltipLabel?: string;
  getOptionSecondaryText?: (option: T) => string;
  renderInput?: AutocompleteProps<T, true, false, false>["renderInput"];
  onChange?: (event: SyntheticEvent, value: T[], reason: string, details?: unknown) => void;
};
export function BoxedMultiselect<T>(props: BoxedMultiselectProps<T>): JSX.Element;
export function BoxedMultiselectFilter<T>(props: BoxedMultiselectProps<T> & { label?: string; placeholder?: string; textFieldProps?: Record<string, unknown> }): JSX.Element;
export function CreatableBoxedMultiselect(props: Omit<BoxedMultiselectProps<string>, "freeSolo"> & { label?: string; placeholder?: string }): JSX.Element;
export function normalizeCreatableValues(values: unknown[]): string[];
export default BoxedMultiselectFilter;
