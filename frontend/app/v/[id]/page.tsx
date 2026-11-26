import { Workspace } from '@/components/Workspace';

export default async function VehiclePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <Workspace vehicleId={decodeURIComponent(id)} />;
}
