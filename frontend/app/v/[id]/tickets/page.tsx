import { VehicleHistory } from '@/components/VehicleHistory';

type Query = Promise<{ [key: string]: string | string[] | undefined }>;

export default async function VehicleTicketsPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Query }) {
  const { id } = await params;
  const { session } = await searchParams;
  return <VehicleHistory vehicleId={decodeURIComponent(id)} tab="tickets" current={typeof session === 'string' ? session : null} />;
}
