/** PL build replacement for the gallery registry: do not bundle solutions. */
import type { ExampleProject } from '../data/examples';
export type { ExampleProject, ExampleBoard } from '../data/examples';
export const exampleProjects: ExampleProject[] = [];
export const getExamplesByCategory = (): ExampleProject[] => [];
export const getExampleById = (): ExampleProject | undefined => undefined;
export const registerProExamples = (): void => {};
export const subscribeProExamples = (): (() => void) => () => {};
export const markProExamplesSettled = (): void => {};
export const areProExamplesSettled = (): boolean => true;
export const getProExamplesVersion = (): number => 0;
export const getCategories = (): ExampleProject['category'][] => [];
