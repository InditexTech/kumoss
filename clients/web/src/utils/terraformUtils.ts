import type { TerraformChange } from '@/types';

export const formatResourceHeader = (change: TerraformChange): string => {
  const resourceName = change.user_friendly_header || change.name || 'Unknown Resource';
  return resourceName.toUpperCase();
};

export const processTerraformPlan = (input: string): Record<string, string> => {
  if (!input) return {};
  const fileRegex = /<([\w.-]+)>([\s\S]*?)<\/\1>/g;
  const files: Record<string, string> = {};
  let match;

  while ((match = fileRegex.exec(input)) !== null) {
    const fileName = match[1];
    if (fileName === 'Terraform_Plan') {
      files[fileName] = match[2].trim() + '\n\n';
    }
  }
  return files;
};

