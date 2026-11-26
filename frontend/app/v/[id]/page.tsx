import { Workspace } from '@/components/Workspace';

type Query = Promise<{ [key: string]: string | string[] | undefined }>;

export default async function VehiclePage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Query }) {
  const { id } = await params;
  const { session } = await searchParams;
  // Проверка в адресе приходит с экрана истории машины: её и разбираем в чате
  return <Workspace vehicleId={decodeURIComponent(id)} initialSession={typeof session === 'string' ? session : null} />;
}
