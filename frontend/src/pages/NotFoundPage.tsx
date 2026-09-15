import { Link } from 'react-router-dom'
import { Content, PageHeader } from '../components/Page'
import { Empty } from '../components/States'

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Not found" />
      <Content>
        <Empty title="This page does not exist" action={<Link to="/" className="btn">Go to Overview</Link>}>
          Check the address, or use the navigation.
        </Empty>
      </Content>
    </>
  )
}
