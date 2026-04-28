import type { ComponentProps } from 'react';
import { GuardControlCenter } from '../../components/GuardControlCenter';

export type GuardPageProps = ComponentProps<typeof GuardControlCenter>;

export function GuardPage(props: GuardPageProps) {
  return <GuardControlCenter {...props} />;
}
