-- Add report_brand_color to organizations for PDF report theming
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS report_brand_color TEXT;
