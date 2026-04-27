import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

type ChartDataItem = { name: string; value: number; unit?: string };
type StructuredChartBlock = {
  chart_type: 'bar' | 'pie' | 'line' | 'radar';
  title?: string;
  data: ChartDataItem[];
};

const COLORS = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#14b8a6'];

export function ResultCharts({ blocks }: { blocks: StructuredChartBlock[] }) {
  if (!blocks.length) return null;

  return (
    <div className="space-y-3">
      {blocks.map((block, idx) => (
        <div key={`${block.chart_type}-${block.title ?? idx}`} className="min-w-[280px] rounded-lg bg-white/50 p-2 dark:bg-background/40">
          {block.title && <p className="mb-1 text-xs font-medium text-gray-500">{block.title}</p>}
          <div className="h-40 w-full">
            <ResponsiveContainer width="100%" height="100%">
              {block.chart_type === 'pie' ? (
                <PieChart>
                  <Pie
                    data={block.data}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={48}
                    label={({ name, value }) => `${name}: ${value}`}
                    labelLine={false}
                  >
                    {block.data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Tooltip formatter={(value, name) => [value, name]} />
                </PieChart>
              ) : block.chart_type === 'radar' ? (
                <RadarChart data={block.data}>
                  <PolarGrid />
                  <PolarAngleAxis dataKey="name" tick={{ fontSize: 10 }} />
                  <Radar dataKey="value" stroke="#6366f1" fill="#6366f1" fillOpacity={0.3} />
                  <Tooltip />
                </RadarChart>
              ) : block.chart_type === 'line' ? (
                <LineChart data={block.data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip formatter={(value, name, item) => [`${value}${item?.payload?.unit ?? ''}`, name as string]} />
                  <Line type="monotone" dataKey="value" stroke="#6366f1" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              ) : (
                <BarChart data={block.data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip formatter={(value, name, item) => [`${value}${item?.payload?.unit ?? ''}`, name as string]} />
                  <Bar dataKey="value" fill="#6366f1" radius={[3, 3, 0, 0]} />
                </BarChart>
              )}
            </ResponsiveContainer>
          </div>
        </div>
      ))}
    </div>
  );
}

export type { StructuredChartBlock };
