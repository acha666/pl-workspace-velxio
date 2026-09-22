/** Custom chips are outside this one-sketch exercise; omit their example code. */
import type { ChipExample } from '../components/customChips/chipExamples';
export type { ChipExample } from '../components/customChips/chipExamples';
export const CHIP_EXAMPLES: ChipExample[] = [];
export const getChipExamples = (): ChipExample[] => [];
export const getChipExamplesVersion = (): number => 0;
export const subscribeChipExamples = (): (() => void) => () => {};
export const registerChipExamples = (): void => {};
export const findExample = (): ChipExample | undefined => undefined;
export const BLANK_CHIP: ChipExample = {
  id: 'blank',
  name: 'Blank',
  description: '',
  category: 'utility',
  sourceC: '',
  chipJson: '{}',
};
